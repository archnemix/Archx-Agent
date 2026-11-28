//! Purpose: Owns the Model Training state machine, §7b launcher host lifecycle, Hardware & Optimization Planner, Tokenizer Arena, Seed/Genesis Provenance Lab, background `sipper` tasks, OS Vault references, and app-scoped persistence.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use iced::Task;
use iced::task::{Handle, sipper};
use serde::{Deserialize, Serialize};
use serde_json::json;
use zeroize::Zeroizing;

use archx_shared::credentials::{Provider, Vault};
use archx_shared::persist::{DisplaySettings, PersistedSettings};
use archx_shared::storage;

use crate::config::{
    ActivationKind, Backbone, ComputeTarget, DatasetSource, DigitPolicy, EmbedScaleMode, InitDist,
    LrSchedule, Mechanism, Modality, NormKind, NormPlacement, OptimizerKind, PosEncoding,
    PreTokenizeMode, PrecisionMode, Preset, ResidualScaleMode, RopeScalingMode, Routing, RunConfig,
    TokenizerKind, UnicodeNorm,
};
use crate::dataset::{PreparedDataset, fetch_remote_dataset, load_local_or_builtin};
use crate::hardware::{
    ComputeBenchmarkReport, HardwareProfile, OptimizationPlan, run_live_compute_benchmark,
};
use crate::repro::{GenesisStateReport, build_and_inspect_genesis, export_provenance_and_genesis};
use crate::rng::{PrngAlgorithm, roll_os_entropy_seed};
use crate::telemetry::{NeuralSnapshot, StepPoint, TelemetryMode};
use crate::tokenizer::{LabTokenizer, TokenPreview, TokenizerArenaRow, run_tokenizer_arena};
use crate::trainer::{
    GenerationEvent, TrainControl, TrainEvent, execute_training_pipeline, generate_from_checkpoint,
};

pub const APP_ID: &str = "training";
pub const AREA_SETTINGS: &str = "settings";
pub const AREA_RUNS: &str = "runs";
pub const AREA_JOURNAL: &str = "journal";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Surface {
    Pipeline,
    NeuralLive,
    Playground,
    Settings,
    Journal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PipelineStage {
    Data,
    Tokenizer,
    Architecture,
    Hardware,
    Repro,
    Train,
}

impl PipelineStage {
    pub const ALL: [Self; 6] = [
        Self::Data,
        Self::Tokenizer,
        Self::Architecture,
        Self::Hardware,
        Self::Repro,
        Self::Train,
    ];

    pub fn code(self) -> &'static str {
        match self {
            Self::Data => "01",
            Self::Tokenizer => "02",
            Self::Architecture => "03",
            Self::Hardware => "04",
            Self::Repro => "05",
            Self::Train => "06",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Data => "Data",
            Self::Tokenizer => "Tokenizer",
            Self::Architecture => "Architecture",
            Self::Hardware => "Hardware & Plan",
            Self::Repro => "Seed & Genesis",
            Self::Train => "Train",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CheckpointChoice {
    Best,
    Latest,
}

impl CheckpointChoice {
    pub fn label(self) -> &'static str {
        match self {
            Self::Best => "best.safetensors",
            Self::Latest => "latest.safetensors",
        }
    }

    pub fn folder(self) -> &'static str {
        match self {
            Self::Best => "best",
            Self::Latest => "latest",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SavedRun {
    pub id: u32,
    pub slug: String,
    pub config: RunConfig,
    pub completed_steps: usize,
    pub best_loss: Option<f32>,
    pub has_best_ckpt: bool,
    pub has_latest_ckpt: bool,
    pub updated_secs: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JournalEntry {
    pub timestamp_secs: u64,
    pub category: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlaygroundTurn {
    pub user: String,
    pub reply_primary: String,
    pub reply_secondary: Option<String>,
}

/// Redacted wrapper so vault input never leaks through `Debug` formatting.
#[derive(Clone, Default)]
pub struct RedactedInput(pub Zeroizing<String>);

impl std::fmt::Debug for RedactedInput {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("[redacted]")
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct StoredSettingsDoc {
    pub hf_vault_slot: Option<u64>,
    pub kaggle_vault_slot: Option<u64>,
    pub default_threads: Option<usize>,
    pub log_loss_chart: bool,
}

#[derive(Debug, Clone)]
pub enum Message {
    // Navigation & host
    OpenSurface(Surface),
    SelectStage(PipelineStage),
    BackToLauncher,
    DismissBanner,

    // Runs management
    NewRun,
    SelectRun(u32),
    DeleteRun(u32),
    EditRunName(String),

    // Stage 01: Data
    SelectDatasetSource(DatasetSource),
    EditLocalPath(String),
    EditHfRepo(String),
    EditHfConfig(String),
    EditHfSplit(String),
    EditKaggleSlug(String),
    EditKaggleFile(String),
    EditCustomUrl(String),
    EditTextField(String),
    EditPromptField(String),
    EditResponseField(String),
    ToggleDeduplicate,
    ToggleDataAdvanced,
    AdjustTrainSplit(i8),
    AdjustShuffleSeed(i64),
    EditShuffleSeed(String),
    EditMinChars(String),
    EditMaxChars(String),
    EditMaxRemoteRows(String),
    PrepareDataset,
    RemoteDatasetLoaded(Result<PreparedDataset, String>),

    // Stage 02: Tokenizer & Side-by-Side Arena
    SelectTokenizerKind(TokenizerKind),
    SelectPreTokenize(PreTokenizeMode),
    SelectDigitPolicy(DigitPolicy),
    SelectUnicodeNorm(UnicodeNorm),
    ToggleByteFallback,
    SelectVocabPadMultiple(usize),
    AdjustSubwordDropout(f32),
    EditCustomSpecials(String),
    EditPretrainedTokenizerPath(String),
    AdjustVocabSize(isize),
    EditVocabSize(String),
    ToggleSequencePacking,
    ToggleBosEos,
    ToggleLowercase,
    ToggleTokenizerAdvanced,
    AdjustMinFreq(isize),
    BuildTokenizer,
    RunTokenizerArena,
    EditTokenizerSample(String),

    // Stage 03: Architecture (Engine #1 Transformer)
    SelectModality(Modality),
    SelectMechanism(Mechanism),
    SelectBackbone(Backbone),
    SelectRouting(Routing),
    SelectPreset(Preset),
    AdjustLayers(isize),
    AdjustDModel(isize),
    AdjustHeads(isize),
    AdjustKvHeads(isize),
    AdjustDff(isize),
    AdjustSeqLen(isize),
    AdjustExperts(isize),
    AdjustTopK(isize),
    AdjustSharedExperts(isize),
    EditMasterSeed(String),
    RandomizeSeed,
    SelectOptimizer(OptimizerKind),
    SelectLrSchedule(LrSchedule),
    EditLearningRate(String),
    AdjustBatchSize(isize),
    AdjustGradAccum(isize),
    AdjustTotalSteps(isize),
    EditTotalSteps(String),
    ToggleExpertAttnDrawer,
    ToggleExpertInitDrawer,
    ToggleExpertStabilityDrawer,
    SelectNorm(NormKind),
    SelectNormPlacement(NormPlacement),
    SelectActivation(ActivationKind),
    SelectPosEncoding(PosEncoding),
    SelectRopeScaling(RopeScalingMode),
    SelectEmbedScale(EmbedScaleMode),
    SelectResidualScaleMode(ResidualScaleMode),
    EditRopeTheta(String),
    ToggleQkNorm,
    ToggleTieEmbeddings,
    ToggleUseBias,
    AdjustSlidingWindow(isize),
    AdjustAttnSoftcap(f32),
    AdjustFinalSoftcap(f32),
    SelectInitDist(InitDist),
    EditInitStd(String),
    AdjustTruncSigma(f32),
    ToggleResidualScale,
    EditAuxLossWeight(String),
    EditZLossWeight(String),
    EditRouterJitter(String),
    EditGradClip(String),
    EditWeightDecay(String),
    EditLabelSmoothing(String),
    ToggleNanRollback,
    AdjustWarmupSteps(isize),
    AdjustEvalEvery(isize),
    AdjustCheckpointEvery(isize),

    // Stage 04: Hardware Inspector, CPU vs GPU Selector, & Custom Optimization Plan
    RescanHardware,
    SelectComputeTarget(ComputeTarget),
    SelectPreferredGpu(usize),
    SelectPrecisionMode(PrecisionMode),
    ToggleActivationCheckpointing,
    ToggleHardwareVocabPad,
    ApplyHardwareOptimizationPlan,
    ExportOptimizationScript,
    RunComputeBenchmark,

    // Stage 05: Seed Hierarchy, Hardware Provenance & Initial Random State (Genesis) Lab
    SelectPrngAlgorithm(PrngAlgorithm),
    ToggleLockSubsystemsToMaster,
    EditWeightSeed(String),
    EditDataSeed(String),
    EditStochasticSeed(String),
    ToggleAutoExportGenesis,
    EditGenesisReloadPath(String),
    InspectGenesisNow,
    ExportProvenanceBundle { include_genesis_weights: bool },

    // Stage 06: Train & Telemetry
    StartTraining,
    TogglePauseTraining,
    RequestCheckpointSave,
    StopTraining,
    ToggleLossLogScale,
    TrainProgress(TrainEvent),
    TrainDone(Result<(), String>),

    // Neural Live View
    SelectTelemetryMode(TelemetryMode),
    SelectInspectedLayer(usize),
    CaptureNeuralSnapshotNow,

    // Playground (Live Chat)
    SelectPlaygroundCheckpoint(CheckpointChoice),
    ToggleAbCompare,
    EditPlaygroundPrompt(String),
    SendPlaygroundPrompt,
    StopGeneration,
    ClearPlaygroundChat,
    AdjustTemperature(f32),
    AdjustTopP(f32),
    AdjustSampleTopK(isize),
    AdjustRepPenalty(f32),
    AdjustMaxNewTokens(isize),
    EditSampleSeed(String),
    GenerationProgress(GenerationEvent),
    GenerationDone(Result<(), String>),

    // Settings & Wipes
    AdjustComputeThreads(isize),
    EditHfSecretInput(RedactedInput),
    SaveHfSecretToVault,
    ClearHfSecretFromVault,
    EditKaggleSecretInput(RedactedInput),
    SaveKaggleSecretToVault,
    ClearKaggleSecretFromVault,
    WipeArea(&'static str),
}

pub struct App {
    /// Read by the launcher after `update`: `true` returns the window to Discover.
    pub left_for_launcher: bool,
    pub display: DisplaySettings,
    pub surface: Surface,
    pub stage: PipelineStage,
    pub banner: Option<(bool, String)>,

    // Runs & active configuration
    pub runs: Vec<SavedRun>,
    pub active_run_id: u32,
    pub next_run_id: u32,
    pub cfg: RunConfig,

    // Draft text inputs for numeric fields so typing is smooth
    pub seed_input: String,
    pub weight_seed_input: String,
    pub data_seed_input: String,
    pub stochastic_seed_input: String,
    pub shuffle_seed_input: String,
    pub vocab_input: String,
    pub lr_input: String,
    pub steps_input: String,
    pub min_chars_input: String,
    pub max_chars_input: String,
    pub max_rows_input: String,
    pub rope_theta_input: String,
    pub init_std_input: String,
    pub aux_loss_input: String,
    pub z_loss_input: String,
    pub jitter_input: String,
    pub grad_clip_input: String,
    pub weight_decay_input: String,
    pub label_smooth_input: String,
    pub sample_seed_input: String,

    // Progressive disclosure drawers
    pub data_advanced_open: bool,
    pub tokenizer_advanced_open: bool,
    pub expert_attn_open: bool,
    pub expert_init_open: bool,
    pub expert_stability_open: bool,

    // Hardware, Optimization Plan, Tokenizer Arena, & Genesis State
    pub hardware: HardwareProfile,
    pub optimization_plan: OptimizationPlan,
    pub compute_benchmark: Option<ComputeBenchmarkReport>,
    pub tokenizer_arena: Vec<TokenizerArenaRow>,
    pub genesis_report: Option<GenesisStateReport>,

    // Prepared pipeline artifacts in memory
    pub dataset: Option<PreparedDataset>,
    pub dataset_busy: bool,
    pub dataset_handle: Option<Handle>,
    pub tokenizer: Option<LabTokenizer>,
    pub tokenizer_sample: String,
    pub tokenizer_preview: TokenPreview,

    // Live training state
    pub training_busy: bool,
    pub training_paused: bool,
    pub train_control: Option<Arc<TrainControl>>,
    pub train_handle: Option<Handle>,
    pub history: Vec<StepPoint>,
    pub log_loss_chart: bool,
    pub telemetry_mode: TelemetryMode,
    pub inspected_layer: usize,
    pub latest_neural: Option<NeuralSnapshot>,

    // Live Playground state
    pub playground_ckpt: CheckpointChoice,
    pub playground_turns: Vec<PlaygroundTurn>,
    pub playground_input: String,
    pub generating: bool,
    pub gen_stop: Arc<AtomicBool>,
    pub gen_handle: Option<Handle>,
    pub streaming_primary: String,
    pub streaming_secondary: String,
    pub last_gen_tps: Option<f32>,

    // Settings, Vault slot ids (never secret values), and journal
    pub hf_vault_slot: Option<u64>,
    pub kaggle_vault_slot: Option<u64>,
    pub hf_secret_draft: RedactedInput,
    pub kaggle_secret_draft: RedactedInput,
    pub journal: Vec<JournalEntry>,
    pub snapshot_mode: bool,
}

impl App {
    /// Host constructor specified by `Adding_An_App.md` §7b.
    pub fn new(persisted: Option<PersistedSettings>) -> Self {
        let snapshot_mode = std::env::var_os("ARCHX_SNAPSHOT").is_some();
        let display = persisted.map(|p| p.display).unwrap_or_default();

        let stored_settings: StoredSettingsDoc = if snapshot_mode {
            StoredSettingsDoc::default()
        } else {
            storage::load_app_body(APP_ID, AREA_SETTINGS)
                .and_then(|v| serde_json::from_value(v).ok())
                .unwrap_or_default()
        };

        let mut runs: Vec<SavedRun> = if snapshot_mode {
            Vec::new()
        } else {
            storage::load_app_body(APP_ID, AREA_RUNS)
                .and_then(|v| v.get("items").cloned())
                .and_then(|v| serde_json::from_value(v).ok())
                .unwrap_or_default()
        };

        let journal: Vec<JournalEntry> = if snapshot_mode {
            Vec::new()
        } else {
            storage::load_app_body(APP_ID, AREA_JOURNAL)
                .and_then(|v| v.get("entries").cloned())
                .and_then(|v| serde_json::from_value(v).ok())
                .unwrap_or_default()
        };

        let hardware = if snapshot_mode {
            HardwareProfile::snapshot_fixture()
        } else {
            HardwareProfile::probe()
        };

        if runs.is_empty() {
            let mut default_cfg = RunConfig::default();
            default_cfg.hyper.compute_threads = stored_settings
                .default_threads
                .unwrap_or(hardware.cpu.recommended_threads)
                .clamp(1, 32);
            runs.push(SavedRun {
                id: 1,
                slug: "run-01-tiny-transformer".to_owned(),
                config: default_cfg,
                completed_steps: 0,
                best_loss: None,
                has_best_ckpt: false,
                has_latest_ckpt: false,
                updated_secs: storage::now_secs(),
            });
        }

        let next_run_id = runs.iter().map(|r| r.id).max().unwrap_or(1) + 1;
        let active = runs[0].clone();
        let sample_text =
            "<user> Compute 2026 * 4 in Rust! <assistant> <think>4 * 2026 = 8104</think> let ans = 8104;"
                .to_owned();

        let initial_ds = load_local_or_builtin(&active.config.dataset).ok();
        let initial_tk = initial_ds
            .as_ref()
            .and_then(|ds| LabTokenizer::train_or_load(&active.config.tokenizer, &ds.train_docs).ok());
        let initial_preview = initial_tk
            .as_ref()
            .map(|tk| tk.preview_text(&sample_text))
            .unwrap_or_default();
        let initial_arena = initial_ds
            .as_ref()
            .map(|ds| {
                run_tokenizer_arena(
                    &active.config.tokenizer,
                    &ds.train_docs,
                    &sample_text,
                    active.config.model.seq_len,
                )
            })
            .unwrap_or_default();

        let optimization_plan = OptimizationPlan::compile(&hardware, &active.config);
        let initial_genesis = build_and_inspect_genesis(&active.config)
            .ok()
            .map(|(_, rep)| rep);

        let mut app = Self {
            left_for_launcher: false,
            display,
            surface: Surface::Pipeline,
            stage: PipelineStage::Data,
            banner: None,
            runs,
            active_run_id: active.id,
            next_run_id,
            cfg: active.config,
            seed_input: String::new(),
            weight_seed_input: String::new(),
            data_seed_input: String::new(),
            stochastic_seed_input: String::new(),
            shuffle_seed_input: String::new(),
            vocab_input: String::new(),
            lr_input: String::new(),
            steps_input: String::new(),
            min_chars_input: String::new(),
            max_chars_input: String::new(),
            max_rows_input: String::new(),
            rope_theta_input: String::new(),
            init_std_input: String::new(),
            aux_loss_input: String::new(),
            z_loss_input: String::new(),
            jitter_input: String::new(),
            grad_clip_input: String::new(),
            weight_decay_input: String::new(),
            label_smooth_input: String::new(),
            sample_seed_input: String::new(),
            data_advanced_open: false,
            tokenizer_advanced_open: true,
            expert_attn_open: true,
            expert_init_open: false,
            expert_stability_open: false,
            hardware,
            optimization_plan,
            compute_benchmark: None,
            tokenizer_arena: initial_arena,
            genesis_report: initial_genesis,
            dataset: initial_ds,
            dataset_busy: false,
            dataset_handle: None,
            tokenizer: initial_tk,
            tokenizer_sample: sample_text,
            tokenizer_preview: initial_preview,
            training_busy: false,
            training_paused: false,
            train_control: None,
            train_handle: None,
            history: Vec::new(),
            log_loss_chart: stored_settings.log_loss_chart,
            telemetry_mode: TelemetryMode::Off,
            inspected_layer: 0,
            latest_neural: None,
            playground_ckpt: CheckpointChoice::Best,
            playground_turns: Vec::new(),
            playground_input: String::new(),
            generating: false,
            gen_stop: Arc::new(AtomicBool::new(false)),
            gen_handle: None,
            streaming_primary: String::new(),
            streaming_secondary: String::new(),
            last_gen_tps: None,
            hf_vault_slot: stored_settings.hf_vault_slot,
            kaggle_vault_slot: stored_settings.kaggle_vault_slot,
            hf_secret_draft: RedactedInput::default(),
            kaggle_secret_draft: RedactedInput::default(),
            journal,
            snapshot_mode,
        };
        app.sync_text_inputs();
        app.refresh_checkpoint_flags();
        app
    }

    /// Host surface switch specified by `Adding_An_App.md` §7b.
    pub fn enter_surface(&mut self, surface: &str) {
        match surface {
            "settings" => self.surface = Surface::Settings,
            "debug" | "journal" => self.surface = Surface::Journal,
            "neural" => self.surface = Surface::NeuralLive,
            "playground" | "chat" => self.surface = Surface::Playground,
            "data" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Data;
            }
            "tokenizer" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Tokenizer;
            }
            "architecture" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Architecture;
            }
            "hardware" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Hardware;
            }
            "repro" | "seed" | "genesis" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Repro;
            }
            "train" => {
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Train;
            }
            _ => self.surface = Surface::Pipeline,
        }
    }

    /// Host exit hook specified by `Adding_An_App.md` §7b: halts background work cleanly.
    pub fn leave_app(&mut self) -> Task<Message> {
        self.abort_all_background_work();
        Task::none()
    }

    /// Deterministic screenshot fixture specified by `Adding_An_App.md` §7b.
    pub fn prepare_snapshot(&mut self, surface: &str) {
        self.snapshot_mode = true;
        self.banner = None;
        self.hardware = HardwareProfile::snapshot_fixture();
        self.enter_surface(surface);
        if let Ok(stage_override) = std::env::var("ARCHX_TRAINING_STAGE") {
            self.enter_surface(stage_override.trim());
        }
        self.optimization_plan = OptimizationPlan::compile(&self.hardware, &self.cfg);
        self.compute_benchmark = Some(ComputeBenchmarkReport {
            matrix_dim: 256,
            cpu_threads: 14,
            cpu_ms: 0.92,
            cpu_gflops: 36.4,
            gpu_adapter_name: Some("Discrete Vulkan / DX12 Compute Adapter".to_owned()),
            gpu_backend: Some("Vulkan / DX12".to_owned()),
            gpu_ms: Some(0.18),
            gpu_gflops: Some(186.5),
            max_abs_diff: Some(1.19e-6),
            recommended_winner: "GPU (Discrete Vulkan / DX12 Compute Adapter · 186.5 GFLOP/s)"
                .to_owned(),
            note: "Verified 256×256 tiled SGEMM: max |CPU − GPU| = 1.19e-6. Hardware GPU WGSL compute pipeline validated.".to_owned(),
        });
        self.history = vec![
            StepPoint {
                step: 1,
                train_loss: 4.82,
                val_loss: Some(4.79),
                perplexity: 123.9,
                lr: 0.001,
                grad_norm: 1.42,
                tokens_per_sec: 3200.0,
            },
            StepPoint {
                step: 20,
                train_loss: 3.14,
                val_loss: Some(3.22),
                perplexity: 23.1,
                lr: 0.0028,
                grad_norm: 0.91,
                tokens_per_sec: 3480.0,
            },
            StepPoint {
                step: 40,
                train_loss: 2.18,
                val_loss: Some(2.31),
                perplexity: 8.84,
                lr: 0.0024,
                grad_norm: 0.64,
                tokens_per_sec: 3510.0,
            },
            StepPoint {
                step: 60,
                train_loss: 1.62,
                val_loss: Some(1.79),
                perplexity: 5.05,
                lr: 0.0015,
                grad_norm: 0.48,
                tokens_per_sec: 3540.0,
            },
        ];
    }

    fn abort_all_background_work(&mut self) {
        if let Some(ctrl) = &self.train_control {
            ctrl.stop.store(true, Ordering::Relaxed);
            ctrl.paused.store(false, Ordering::Relaxed);
        }
        if let Some(h) = self.train_handle.take() {
            h.abort();
        }
        self.training_busy = false;
        self.training_paused = false;

        self.gen_stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.gen_handle.take() {
            h.abort();
        }
        self.generating = false;

        if let Some(h) = self.dataset_handle.take() {
            h.abort();
        }
        self.dataset_busy = false;
    }

    fn sync_text_inputs(&mut self) {
        self.seed_input = self.cfg.hyper.master_seed.to_string();
        self.weight_seed_input = self.cfg.seeds.effective_weight_seed().to_string();
        self.data_seed_input = self.cfg.seeds.effective_data_seed().to_string();
        self.stochastic_seed_input = self.cfg.seeds.effective_stochastic_seed().to_string();
        self.shuffle_seed_input = self.cfg.dataset.shuffle_seed.to_string();
        self.vocab_input = self.cfg.tokenizer.vocab_size.to_string();
        self.lr_input = format!("{:.4}", self.cfg.hyper.lr);
        self.steps_input = self.cfg.hyper.total_steps.to_string();
        self.min_chars_input = self.cfg.dataset.min_chars.to_string();
        self.max_chars_input = self.cfg.dataset.max_chars.to_string();
        self.max_rows_input = self.cfg.dataset.max_remote_rows.to_string();
        self.rope_theta_input = format!("{:.0}", self.cfg.model.rope_theta);
        self.init_std_input = format!("{:.3}", self.cfg.model.init_std);
        self.aux_loss_input = format!("{:.3}", self.cfg.model.moe.aux_loss_weight);
        self.z_loss_input = format!("{:.4}", self.cfg.model.moe.z_loss_weight);
        self.jitter_input = format!("{:.3}", self.cfg.model.moe.router_jitter);
        self.grad_clip_input = format!("{:.2}", self.cfg.hyper.grad_clip_norm);
        self.weight_decay_input = format!("{:.3}", self.cfg.hyper.weight_decay);
        self.label_smooth_input = format!("{:.2}", self.cfg.hyper.label_smoothing);
        self.sample_seed_input = self.cfg.sampling.seed.to_string();
    }

    pub fn active_run(&self) -> Option<&SavedRun> {
        self.runs.iter().find(|r| r.id == self.active_run_id)
    }

    pub fn active_run_dir(&self) -> PathBuf {
        let slug = self
            .active_run()
            .map(|r| r.slug.as_str())
            .unwrap_or("run-01-tiny-transformer");
        storage::app_dir(APP_ID)
            .unwrap_or_else(|| std::env::temp_dir().join("archx-training"))
            .join("checkpoints")
            .join(slug)
    }

    fn refresh_checkpoint_flags(&mut self) {
        let base = storage::app_dir(APP_ID)
            .unwrap_or_else(|| std::env::temp_dir().join("archx-training"))
            .join("checkpoints");
        for run in &mut self.runs {
            let dir = base.join(&run.slug);
            run.has_best_ckpt = dir.join("best/model.safetensors").is_file();
            run.has_latest_ckpt = dir.join("latest/model.safetensors").is_file();
        }
    }

    fn recompute_plan(&mut self) {
        self.optimization_plan = OptimizationPlan::compile(&self.hardware, &self.cfg);
    }

    fn sync_active_run_record(&mut self) {
        self.recompute_plan();
        if let Some(run) = self.runs.iter_mut().find(|r| r.id == self.active_run_id) {
            run.config = self.cfg.clone();
            run.updated_secs = storage::now_secs();
        }
        self.persist_runs();
    }

    fn log_event(&mut self, category: &str, detail: impl Into<String>) {
        self.journal.push(JournalEntry {
            timestamp_secs: storage::now_secs(),
            category: category.to_owned(),
            detail: detail.into(),
        });
        if self.journal.len() > 250 {
            let drop_n = self.journal.len() - 250;
            self.journal.drain(0..drop_n);
        }
        self.persist_journal();
    }

    fn persist_settings(&self) {
        if self.snapshot_mode {
            return;
        }
        let doc = StoredSettingsDoc {
            hf_vault_slot: self.hf_vault_slot,
            kaggle_vault_slot: self.kaggle_vault_slot,
            default_threads: Some(self.cfg.hyper.compute_threads),
            log_loss_chart: self.log_loss_chart,
        };
        if let Ok(val) = serde_json::to_value(doc) {
            let _ = storage::save_app(APP_ID, AREA_SETTINGS, val);
        }
    }

    fn persist_runs(&self) {
        if self.snapshot_mode {
            return;
        }
        if let Ok(items) = serde_json::to_value(&self.runs) {
            let _ = storage::save_app(APP_ID, AREA_RUNS, json!({ "items": items }));
        }
    }

    fn persist_journal(&self) {
        if self.snapshot_mode {
            return;
        }
        if let Ok(entries) = serde_json::to_value(&self.journal) {
            let _ = storage::save_app(APP_ID, AREA_JOURNAL, json!({ "entries": entries }));
        }
    }

    fn read_vault_slot(slot: Option<u64>) -> Option<Zeroizing<String>> {
        let id = slot?;
        Vault::os()
            .with_key(Provider::Custom, id, |s| Zeroizing::new(s.to_owned()))
            .ok()
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        self.left_for_launcher = false;
        match message {
            Message::OpenSurface(s) => {
                self.surface = s;
                self.refresh_checkpoint_flags();
            }
            Message::SelectStage(st) => self.stage = st,
            Message::BackToLauncher => {
                if self.snapshot_mode {
                    return Task::none();
                }
                let task = self.leave_app();
                self.left_for_launcher = true;
                return task;
            }
            Message::DismissBanner => self.banner = None,

            // Runs
            Message::NewRun => {
                if self.training_busy {
                    self.banner = Some((
                        false,
                        "Stop the active training run before creating a new run.".into(),
                    ));
                    return Task::none();
                }
                let id = self.next_run_id;
                self.next_run_id += 1;
                let mut cfg = RunConfig::default();
                cfg.name = format!("transformer-run-{id:02}");
                cfg.hyper.compute_threads = self.cfg.hyper.compute_threads;
                let slug = format!("run-{id:02}");
                self.runs.push(SavedRun {
                    id,
                    slug,
                    config: cfg.clone(),
                    completed_steps: 0,
                    best_loss: None,
                    has_best_ckpt: false,
                    has_latest_ckpt: false,
                    updated_secs: storage::now_secs(),
                });
                self.active_run_id = id;
                self.cfg = cfg;
                self.history.clear();
                self.latest_neural = None;
                self.playground_turns.clear();
                self.sync_text_inputs();
                self.recompute_plan();
                self.genesis_report = build_and_inspect_genesis(&self.cfg).ok().map(|(_, r)| r);
                self.persist_runs();
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Data;
            }
            Message::SelectRun(id) => {
                if self.training_busy {
                    self.banner = Some((false, "Pause or stop training before switching runs.".into()));
                    return Task::none();
                }
                if let Some(found) = self.runs.iter().find(|r| r.id == id).cloned() {
                    self.active_run_id = id;
                    self.cfg = found.config;
                    self.history.clear();
                    self.latest_neural = None;
                    self.playground_turns.clear();
                    self.sync_text_inputs();
                    self.recompute_plan();
                    self.genesis_report = build_and_inspect_genesis(&self.cfg).ok().map(|(_, r)| r);
                    self.refresh_checkpoint_flags();
                    if self.cfg.dataset.source.is_builtin() {
                        if let Ok(ds) = load_local_or_builtin(&self.cfg.dataset) {
                            if let Ok(tk) = LabTokenizer::train_or_load(&self.cfg.tokenizer, &ds.train_docs)
                            {
                                self.tokenizer_preview = tk.preview_text(&self.tokenizer_sample);
                                self.tokenizer = Some(tk);
                            }
                            self.dataset = Some(ds);
                        }
                    }
                }
            }
            Message::DeleteRun(id) => {
                if self.training_busy && self.active_run_id == id {
                    self.banner = Some((false, "Cannot delete the run that is currently training.".into()));
                    return Task::none();
                }
                if self.runs.len() <= 1 {
                    self.banner = Some((false, "At least one workspace run is kept.".into()));
                    return Task::none();
                }
                if let Some(removed) = self.runs.iter().find(|r| r.id == id) {
                    if let Some(app_root) = storage::app_dir(APP_ID) {
                        let _ = std::fs::remove_dir_all(app_root.join("checkpoints").join(&removed.slug));
                    }
                }
                self.runs.retain(|r| r.id != id);
                if self.active_run_id == id {
                    let first = self.runs[0].clone();
                    self.active_run_id = first.id;
                    self.cfg = first.config;
                    self.sync_text_inputs();
                    self.recompute_plan();
                }
                self.persist_runs();
            }
            Message::EditRunName(name) => {
                self.cfg.name = name.chars().take(48).collect();
                self.sync_active_run_record();
            }

            // Stage 01: Data
            Message::SelectDatasetSource(src) => {
                self.cfg.dataset.source = src;
                if src.is_builtin() {
                    if let Ok(ds) = load_local_or_builtin(&self.cfg.dataset) {
                        self.dataset = Some(ds);
                    }
                }
                self.sync_active_run_record();
            }
            Message::EditLocalPath(v) => {
                self.cfg.dataset.local_path = v;
                self.sync_active_run_record();
            }
            Message::EditHfRepo(v) => {
                self.cfg.dataset.hf_repo = v;
                self.sync_active_run_record();
            }
            Message::EditHfConfig(v) => {
                self.cfg.dataset.hf_config = v;
                self.sync_active_run_record();
            }
            Message::EditHfSplit(v) => {
                self.cfg.dataset.hf_split = v;
                self.sync_active_run_record();
            }
            Message::EditKaggleSlug(v) => {
                self.cfg.dataset.kaggle_slug = v;
                self.sync_active_run_record();
            }
            Message::EditKaggleFile(v) => {
                self.cfg.dataset.kaggle_file = v;
                self.sync_active_run_record();
            }
            Message::EditCustomUrl(v) => {
                self.cfg.dataset.custom_url = v;
                self.sync_active_run_record();
            }
            Message::EditTextField(v) => {
                self.cfg.dataset.text_field = v;
                self.sync_active_run_record();
            }
            Message::EditPromptField(v) => {
                self.cfg.dataset.prompt_field = v;
                self.sync_active_run_record();
            }
            Message::EditResponseField(v) => {
                self.cfg.dataset.response_field = v;
                self.sync_active_run_record();
            }
            Message::ToggleDeduplicate => {
                self.cfg.dataset.deduplicate = !self.cfg.dataset.deduplicate;
                self.sync_active_run_record();
            }
            Message::ToggleDataAdvanced => self.data_advanced_open = !self.data_advanced_open,
            Message::AdjustTrainSplit(delta) => {
                let next =
                    (i16::from(self.cfg.dataset.train_pct) + i16::from(delta)).clamp(50, 95) as u8;
                self.cfg.dataset.train_pct = next;
                self.cfg.dataset.val_pct = 100 - next;
                self.sync_active_run_record();
            }
            Message::AdjustShuffleSeed(delta) => {
                let next = (self.cfg.dataset.shuffle_seed as i64 + delta).max(0) as u64;
                self.cfg.dataset.shuffle_seed = next;
                self.shuffle_seed_input = next.to_string();
                self.sync_active_run_record();
            }
            Message::EditShuffleSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.dataset.shuffle_seed = v;
                    self.sync_active_run_record();
                }
                self.shuffle_seed_input = s;
            }
            Message::EditMinChars(s) => {
                if let Ok(v) = s.trim().parse::<usize>() {
                    self.cfg.dataset.min_chars = v.min(4096);
                    self.sync_active_run_record();
                }
                self.min_chars_input = s;
            }
            Message::EditMaxChars(s) => {
                if let Ok(v) = s.trim().parse::<usize>() {
                    self.cfg.dataset.max_chars = v.clamp(16, 1_000_000);
                    self.sync_active_run_record();
                }
                self.max_chars_input = s;
            }
            Message::EditMaxRemoteRows(s) => {
                if let Ok(v) = s.trim().parse::<usize>() {
                    self.cfg.dataset.max_remote_rows = v.clamp(10, 5000);
                    self.sync_active_run_record();
                }
                self.max_rows_input = s;
            }
            Message::PrepareDataset => {
                let ds_cfg = self.cfg.dataset.clone();
                if ds_cfg.source.is_builtin() || ds_cfg.source == DatasetSource::LocalPath {
                    match load_local_or_builtin(&ds_cfg) {
                        Ok(ds) => {
                            let summary = format!(
                                "Prepared {}: {} train / {} val documents.",
                                ds.source_label,
                                ds.train_docs.len(),
                                ds.val_docs.len()
                            );
                            self.log_event("dataset", &summary);
                            self.banner = Some((true, summary));
                            self.dataset = Some(ds);
                        }
                        Err(err) => {
                            self.log_event("dataset-error", &err);
                            self.banner = Some((false, err));
                        }
                    }
                } else {
                    if let Some(h) = self.dataset_handle.take() {
                        h.abort();
                    }
                    self.dataset_busy = true;
                    let secret = match ds_cfg.source {
                        DatasetSource::HuggingFaceHub | DatasetSource::CustomUrl => {
                            Self::read_vault_slot(self.hf_vault_slot)
                        }
                        DatasetSource::KaggleDataset => Self::read_vault_slot(self.kaggle_vault_slot),
                        _ => None,
                    };
                    let task = Task::perform(
                        async move { fetch_remote_dataset(ds_cfg, secret).await },
                        Message::RemoteDatasetLoaded,
                    );
                    let (task, handle) = task.abortable();
                    self.dataset_handle = Some(handle);
                    return task;
                }
            }
            Message::RemoteDatasetLoaded(res) => {
                self.dataset_busy = false;
                self.dataset_handle = None;
                match res {
                    Ok(ds) => {
                        let msg = format!(
                            "Fetched {}: {} train / {} val rows.",
                            ds.source_label,
                            ds.train_docs.len(),
                            ds.val_docs.len()
                        );
                        self.log_event("dataset", &msg);
                        self.banner = Some((true, msg));
                        self.dataset = Some(ds);
                    }
                    Err(err) => {
                        self.log_event("dataset-error", &err);
                        self.banner = Some((false, err));
                    }
                }
            }

            // Stage 02: Tokenizer & 4-Way Arena
            Message::SelectTokenizerKind(kind) => {
                self.cfg.tokenizer.kind = kind;
                if kind == TokenizerKind::ByteLevelBpe && self.cfg.tokenizer.vocab_size < 320 {
                    self.cfg.tokenizer.vocab_size = 512;
                    self.vocab_input = "512".into();
                }
                self.sync_active_run_record();
            }
            Message::SelectPreTokenize(m) => {
                self.cfg.tokenizer.pre_tokenize = m;
                self.sync_active_run_record();
            }
            Message::SelectDigitPolicy(dp) => {
                self.cfg.tokenizer.digit_policy = dp;
                self.sync_active_run_record();
            }
            Message::SelectUnicodeNorm(un) => {
                self.cfg.tokenizer.normalization = un;
                self.cfg.tokenizer.lowercase = un == UnicodeNorm::Lowercase;
                self.sync_active_run_record();
            }
            Message::ToggleByteFallback => {
                self.cfg.tokenizer.byte_fallback = !self.cfg.tokenizer.byte_fallback;
                self.sync_active_run_record();
            }
            Message::SelectVocabPadMultiple(mult) => {
                self.cfg.tokenizer.pad_to_multiple = mult;
                self.sync_active_run_record();
            }
            Message::AdjustSubwordDropout(delta) => {
                self.cfg.tokenizer.subword_dropout =
                    (self.cfg.tokenizer.subword_dropout + delta).clamp(0.0, 0.25);
                self.sync_active_run_record();
            }
            Message::EditCustomSpecials(s) => {
                self.cfg.tokenizer.custom_special_tokens = s.chars().take(180).collect();
                self.sync_active_run_record();
            }
            Message::EditPretrainedTokenizerPath(v) => {
                self.cfg.tokenizer.pretrained_path = v;
                self.sync_active_run_record();
            }
            Message::AdjustVocabSize(delta) => {
                let next =
                    (self.cfg.tokenizer.vocab_size as isize + delta).clamp(48, 32_768) as usize;
                self.cfg.tokenizer.vocab_size = next;
                self.vocab_input = next.to_string();
                self.sync_active_run_record();
            }
            Message::EditVocabSize(s) => {
                if let Ok(v) = s.trim().parse::<usize>() {
                    self.cfg.tokenizer.vocab_size = v.clamp(32, 65_536);
                    self.sync_active_run_record();
                }
                self.vocab_input = s;
            }
            Message::ToggleSequencePacking => {
                self.cfg.tokenizer.sequence_packing = !self.cfg.tokenizer.sequence_packing;
                self.sync_active_run_record();
            }
            Message::ToggleBosEos => {
                self.cfg.tokenizer.add_bos_eos = !self.cfg.tokenizer.add_bos_eos;
                self.sync_active_run_record();
            }
            Message::ToggleLowercase => {
                self.cfg.tokenizer.lowercase = !self.cfg.tokenizer.lowercase;
                if self.cfg.tokenizer.lowercase {
                    self.cfg.tokenizer.normalization = UnicodeNorm::Lowercase;
                } else if self.cfg.tokenizer.normalization == UnicodeNorm::Lowercase {
                    self.cfg.tokenizer.normalization = UnicodeNorm::None;
                }
                self.sync_active_run_record();
            }
            Message::ToggleTokenizerAdvanced => {
                self.tokenizer_advanced_open = !self.tokenizer_advanced_open;
            }
            Message::AdjustMinFreq(delta) => {
                let next =
                    (self.cfg.tokenizer.min_frequency as isize + delta).clamp(1, 50) as usize;
                self.cfg.tokenizer.min_frequency = next;
                self.sync_active_run_record();
            }
            Message::BuildTokenizer => {
                if self.dataset.is_none() {
                    if let Ok(ds) = load_local_or_builtin(&self.cfg.dataset) {
                        self.dataset = Some(ds);
                    }
                }
                let docs = self
                    .dataset
                    .as_ref()
                    .map(|d| d.train_docs.as_slice())
                    .unwrap_or(&[]);
                if docs.is_empty() && self.cfg.tokenizer.kind != TokenizerKind::PretrainedFile {
                    self.banner = Some((
                        false,
                        "Prepare a dataset in Stage 01 before training a tokenizer.".into(),
                    ));
                    return Task::none();
                }
                match LabTokenizer::train_or_load(&self.cfg.tokenizer, docs) {
                    Ok(tk) => {
                        self.cfg.model.vocab_size = tk.vocab_size();
                        self.tokenizer_preview = tk.preview_text(&self.tokenizer_sample);
                        let summary = format!("Tokenizer ready: {}.", tk.summary());
                        self.tokenizer = Some(tk);
                        self.log_event("tokenizer", &summary);
                        self.banner = Some((true, summary));
                        self.sync_active_run_record();
                    }
                    Err(err) => {
                        self.log_event("tokenizer-error", &err);
                        self.banner = Some((false, err));
                    }
                }
            }
            Message::RunTokenizerArena => {
                if self.dataset.is_none() {
                    if let Ok(ds) = load_local_or_builtin(&self.cfg.dataset) {
                        self.dataset = Some(ds);
                    }
                }
                let docs = self
                    .dataset
                    .as_ref()
                    .map(|d| d.train_docs.as_slice())
                    .unwrap_or(&[]);
                if docs.is_empty() {
                    self.banner = Some((
                        false,
                        "Prepare a dataset first to benchmark all 4 scratch tokenizers.".into(),
                    ));
                    return Task::none();
                }
                self.tokenizer_arena = run_tokenizer_arena(
                    &self.cfg.tokenizer,
                    docs,
                    &self.tokenizer_sample,
                    self.cfg.model.seq_len,
                );
                let msg = format!(
                    "Compared all 4 scratch tokenizers ({} rules, {} digits) on active corpus.",
                    self.cfg.tokenizer.pre_tokenize.label(),
                    self.cfg.tokenizer.digit_policy.label()
                );
                self.log_event("tokenizer-arena", &msg);
                self.banner = Some((true, msg));
            }
            Message::EditTokenizerSample(s) => {
                self.tokenizer_sample = s;
                if let Some(tk) = &self.tokenizer {
                    self.tokenizer_preview = tk.preview_text(&self.tokenizer_sample);
                }
            }

            // Stage 03: Architecture
            Message::SelectModality(m) => {
                if m.is_live_in_slice() {
                    self.cfg.modality = m;
                    self.sync_active_run_record();
                } else {
                    self.banner = Some((
                        false,
                        format!(
                            "{} arrives in upcoming engines (see Roadmap.md). Engine #1 focuses on Text · Transformer.",
                            m.label()
                        ),
                    ));
                }
            }
            Message::SelectMechanism(mech) => {
                if mech.is_live_in_slice() {
                    self.cfg.mechanism = mech;
                    self.sync_active_run_record();
                } else {
                    self.banner = Some((
                        false,
                        format!(
                            "{} arrives in upcoming engines (see Roadmap.md). Engine #1 focuses on Autoregressive Transformer.",
                            mech.label()
                        ),
                    ));
                }
            }
            Message::SelectBackbone(bb) => {
                if bb.is_live_in_slice() {
                    self.cfg.backbone = bb;
                    self.sync_active_run_record();
                } else {
                    self.banner = Some((
                        false,
                        format!(
                            "{} arrives in upcoming engines (see Roadmap.md). Engine #1 is the Transformer Engine (Dense & MoE).",
                            bb.label()
                        ),
                    ));
                }
            }
            Message::SelectRouting(r) => {
                self.cfg.model.routing = r;
                self.sync_active_run_record();
            }
            Message::SelectPreset(preset) => {
                self.cfg.preset = preset;
                if preset != Preset::Custom {
                    let keep_vocab = self.cfg.model.vocab_size;
                    let keep_routing = self.cfg.model.routing;
                    let keep_moe = self.cfg.model.moe.clone();
                    let keep_algo = self.cfg.model.prng_algorithm;
                    let mut next_model =
                        crate::config::TransformerConfig::from_preset(preset, keep_routing);
                    next_model.vocab_size = keep_vocab;
                    next_model.moe = keep_moe;
                    next_model.prng_algorithm = keep_algo;
                    self.cfg.model = next_model;
                    self.sync_text_inputs();
                }
                self.sync_active_run_record();
            }
            Message::AdjustLayers(delta) => {
                self.cfg.preset = Preset::Custom;
                self.cfg.model.n_layers =
                    (self.cfg.model.n_layers as isize + delta).clamp(1, 32) as usize;
                if self.inspected_layer >= self.cfg.model.n_layers {
                    self.inspected_layer = self.cfg.model.n_layers - 1;
                }
                self.sync_active_run_record();
            }
            Message::AdjustDModel(delta) => {
                self.cfg.preset = Preset::Custom;
                let step = (self.cfg.model.n_heads * 2).max(8) as isize;
                self.cfg.model.d_model =
                    (self.cfg.model.d_model as isize + delta * step).clamp(32, 2048) as usize;
                self.cfg.model = self.cfg.model.sanitized();
                self.sync_active_run_record();
            }
            Message::AdjustHeads(delta) => {
                self.cfg.preset = Preset::Custom;
                self.cfg.model.n_heads =
                    (self.cfg.model.n_heads as isize + delta).clamp(1, 32) as usize;
                self.cfg.model = self.cfg.model.sanitized();
                self.sync_active_run_record();
            }
            Message::AdjustKvHeads(delta) => {
                self.cfg.preset = Preset::Custom;
                let cur = self.cfg.model.n_kv_heads as isize;
                let mut cand = (cur + delta).clamp(1, self.cfg.model.n_heads as isize) as usize;
                while self.cfg.model.n_heads % cand != 0 && cand > 1 && cand < self.cfg.model.n_heads
                {
                    if delta >= 0 {
                        cand += 1;
                    } else {
                        cand -= 1;
                    }
                }
                self.cfg.model.n_kv_heads = cand.clamp(1, self.cfg.model.n_heads);
                self.sync_active_run_record();
            }
            Message::AdjustDff(delta) => {
                self.cfg.preset = Preset::Custom;
                self.cfg.model.d_ff =
                    (self.cfg.model.d_ff as isize + delta).clamp(64, 8192) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustSeqLen(delta) => {
                self.cfg.preset = Preset::Custom;
                self.cfg.model.seq_len =
                    (self.cfg.model.seq_len as isize + delta).clamp(16, 2048) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustExperts(delta) => {
                self.cfg.model.moe.n_experts =
                    (self.cfg.model.moe.n_experts as isize + delta).clamp(2, 16) as usize;
                self.cfg.model.moe.top_k = self.cfg.model.moe.top_k.min(self.cfg.model.moe.n_experts);
                self.sync_active_run_record();
            }
            Message::AdjustTopK(delta) => {
                self.cfg.model.moe.top_k = (self.cfg.model.moe.top_k as isize + delta)
                    .clamp(1, self.cfg.model.moe.n_experts as isize)
                    as usize;
                self.sync_active_run_record();
            }
            Message::AdjustSharedExperts(delta) => {
                self.cfg.model.moe.n_shared_experts =
                    (self.cfg.model.moe.n_shared_experts as isize + delta).clamp(0, 4) as usize;
                self.sync_active_run_record();
            }
            Message::EditMasterSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.hyper.master_seed = v;
                    self.cfg.seeds.master_seed = v;
                    self.cfg.seeds.sync_from_master();
                    self.cfg.model.init_seed = self.cfg.seeds.effective_weight_seed();
                    self.weight_seed_input = self.cfg.seeds.effective_weight_seed().to_string();
                    self.data_seed_input = self.cfg.seeds.effective_data_seed().to_string();
                    self.stochastic_seed_input =
                        self.cfg.seeds.effective_stochastic_seed().to_string();
                    self.sync_active_run_record();
                }
                self.seed_input = s;
            }
            Message::RandomizeSeed => {
                let next = roll_os_entropy_seed();
                self.cfg.hyper.master_seed = next;
                self.cfg.seeds.master_seed = next;
                self.cfg.seeds.sync_from_master();
                self.cfg.model.init_seed = self.cfg.seeds.effective_weight_seed();
                self.sync_text_inputs();
                self.genesis_report = build_and_inspect_genesis(&self.cfg).ok().map(|(_, r)| r);
                self.sync_active_run_record();
            }
            Message::SelectOptimizer(opt) => {
                self.cfg.hyper.optimizer = opt;
                self.sync_active_run_record();
            }
            Message::SelectLrSchedule(sched) => {
                self.cfg.hyper.lr_schedule = sched;
                self.sync_active_run_record();
            }
            Message::EditLearningRate(s) => {
                if let Ok(v) = s.trim().parse::<f64>() {
                    if v > 0.0 && v <= 1.0 {
                        self.cfg.hyper.lr = v;
                        self.sync_active_run_record();
                    }
                }
                self.lr_input = s;
            }
            Message::AdjustBatchSize(delta) => {
                self.cfg.hyper.batch_size =
                    (self.cfg.hyper.batch_size as isize + delta).clamp(1, 64) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustGradAccum(delta) => {
                self.cfg.hyper.grad_accum_steps =
                    (self.cfg.hyper.grad_accum_steps as isize + delta).clamp(1, 32) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustTotalSteps(delta) => {
                let next = (self.cfg.hyper.total_steps as isize + delta).clamp(10, 50_000) as usize;
                self.cfg.hyper.total_steps = next;
                self.steps_input = next.to_string();
                self.sync_active_run_record();
            }
            Message::EditTotalSteps(s) => {
                if let Ok(v) = s.trim().parse::<usize>() {
                    self.cfg.hyper.total_steps = v.clamp(5, 100_000);
                    self.sync_active_run_record();
                }
                self.steps_input = s;
            }
            Message::ToggleExpertAttnDrawer => self.expert_attn_open = !self.expert_attn_open,
            Message::ToggleExpertInitDrawer => self.expert_init_open = !self.expert_init_open,
            Message::ToggleExpertStabilityDrawer => {
                self.expert_stability_open = !self.expert_stability_open;
            }
            Message::SelectNorm(n) => {
                self.cfg.model.norm = n;
                self.sync_active_run_record();
            }
            Message::SelectNormPlacement(np) => {
                self.cfg.model.norm_placement = np;
                self.sync_active_run_record();
            }
            Message::SelectActivation(act) => {
                self.cfg.model.activation = act;
                self.sync_active_run_record();
            }
            Message::SelectPosEncoding(pe) => {
                self.cfg.model.pos_encoding = pe;
                self.sync_active_run_record();
            }
            Message::SelectRopeScaling(rs) => {
                self.cfg.model.rope_scaling = rs;
                self.sync_active_run_record();
            }
            Message::SelectEmbedScale(es) => {
                self.cfg.model.embed_scale = es;
                self.sync_active_run_record();
            }
            Message::SelectResidualScaleMode(rsm) => {
                self.cfg.model.residual_scale = rsm != ResidualScaleMode::Standard;
                self.cfg.model.residual_scale_mode = rsm;
                self.sync_active_run_record();
            }
            Message::EditRopeTheta(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (100.0..=5_000_000.0).contains(&v) {
                        self.cfg.model.rope_theta = v;
                        self.sync_active_run_record();
                    }
                }
                self.rope_theta_input = s;
            }
            Message::ToggleQkNorm => {
                self.cfg.model.qk_norm = !self.cfg.model.qk_norm;
                self.sync_active_run_record();
            }
            Message::ToggleTieEmbeddings => {
                self.cfg.model.tie_embeddings = !self.cfg.model.tie_embeddings;
                self.sync_active_run_record();
            }
            Message::ToggleUseBias => {
                self.cfg.model.use_bias = !self.cfg.model.use_bias;
                self.sync_active_run_record();
            }
            Message::AdjustSlidingWindow(delta) => {
                let next = (self.cfg.model.sliding_window as isize + delta).clamp(0, 2048) as usize;
                self.cfg.model.sliding_window = next;
                self.sync_active_run_record();
            }
            Message::AdjustAttnSoftcap(delta) => {
                let next = (self.cfg.model.attn_logit_softcap + delta).clamp(0.0, 100.0);
                self.cfg.model.attn_logit_softcap = if next < 2.0 { 0.0 } else { next };
                self.sync_active_run_record();
            }
            Message::AdjustFinalSoftcap(delta) => {
                let next = (self.cfg.model.final_logit_softcap + delta).clamp(0.0, 100.0);
                self.cfg.model.final_logit_softcap = if next < 2.0 { 0.0 } else { next };
                self.sync_active_run_record();
            }
            Message::SelectInitDist(d) => {
                self.cfg.model.init_dist = d;
                self.sync_active_run_record();
            }
            Message::EditInitStd(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.001..=0.25).contains(&v) {
                        self.cfg.model.init_std = v;
                        self.sync_active_run_record();
                    }
                }
                self.init_std_input = s;
            }
            Message::AdjustTruncSigma(delta) => {
                self.cfg.model.truncated_sigma =
                    (self.cfg.model.truncated_sigma + delta).clamp(1.0, 4.5);
                self.sync_active_run_record();
            }
            Message::ToggleResidualScale => {
                self.cfg.model.residual_scale = !self.cfg.model.residual_scale;
                self.sync_active_run_record();
            }
            Message::EditAuxLossWeight(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.0..=1.0).contains(&v) {
                        self.cfg.model.moe.aux_loss_weight = v;
                        self.sync_active_run_record();
                    }
                }
                self.aux_loss_input = s;
            }
            Message::EditZLossWeight(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.0..=0.5).contains(&v) {
                        self.cfg.model.moe.z_loss_weight = v;
                        self.sync_active_run_record();
                    }
                }
                self.z_loss_input = s;
            }
            Message::EditRouterJitter(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.0..=0.25).contains(&v) {
                        self.cfg.model.moe.router_jitter = v;
                        self.sync_active_run_record();
                    }
                }
                self.jitter_input = s;
            }
            Message::EditGradClip(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.0..=50.0).contains(&v) {
                        self.cfg.hyper.grad_clip_norm = v;
                        self.sync_active_run_record();
                    }
                }
                self.grad_clip_input = s;
            }
            Message::EditWeightDecay(s) => {
                if let Ok(v) = s.trim().parse::<f64>() {
                    if (0.0..=1.0).contains(&v) {
                        self.cfg.hyper.weight_decay = v;
                        self.sync_active_run_record();
                    }
                }
                self.weight_decay_input = s;
            }
            Message::EditLabelSmoothing(s) => {
                if let Ok(v) = s.trim().parse::<f32>() {
                    if (0.0..=0.25).contains(&v) {
                        self.cfg.hyper.label_smoothing = v;
                        self.sync_active_run_record();
                    }
                }
                self.label_smooth_input = s;
            }
            Message::ToggleNanRollback => {
                self.cfg.hyper.nan_rollback = !self.cfg.hyper.nan_rollback;
                self.sync_active_run_record();
            }
            Message::AdjustWarmupSteps(delta) => {
                self.cfg.hyper.warmup_steps =
                    (self.cfg.hyper.warmup_steps as isize + delta).clamp(0, 10_000) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustEvalEvery(delta) => {
                self.cfg.hyper.eval_every =
                    (self.cfg.hyper.eval_every as isize + delta).clamp(5, 1000) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustCheckpointEvery(delta) => {
                self.cfg.hyper.checkpoint_every =
                    (self.cfg.hyper.checkpoint_every as isize + delta).clamp(5, 2000) as usize;
                self.sync_active_run_record();
            }

            // Stage 04: Hardware & Custom Optimization Plan
            Message::RescanHardware => {
                self.hardware = HardwareProfile::probe();
                self.recompute_plan();
                let gpu_count = self.hardware.gpus.len();
                let msg = format!(
                    "Probed host: {} ({} cores, {}), {} MB RAM, {gpu_count} WGPU adapter(s).",
                    self.hardware.cpu.brand,
                    self.hardware.cpu.logical_cores,
                    self.hardware.cpu.simd_tier(),
                    self.hardware.memory.total_ram_mb
                );
                self.log_event("hardware", &msg);
                self.banner = Some((true, msg));
            }
            Message::SelectComputeTarget(target) => {
                self.cfg.hardware_exec.target = target;
                self.sync_active_run_record();
            }
            Message::SelectPreferredGpu(idx) => {
                self.cfg.hardware_exec.preferred_gpu_index = idx;
                self.cfg.hardware_exec.target = ComputeTarget::Gpu;
                self.sync_active_run_record();
            }
            Message::SelectPrecisionMode(pm) => {
                self.cfg.hardware_exec.precision = pm;
                self.sync_active_run_record();
            }
            Message::ToggleActivationCheckpointing => {
                self.cfg.hardware_exec.activation_checkpointing =
                    !self.cfg.hardware_exec.activation_checkpointing;
                self.sync_active_run_record();
            }
            Message::ToggleHardwareVocabPad => {
                self.cfg.hardware_exec.pad_vocab_for_hardware =
                    !self.cfg.hardware_exec.pad_vocab_for_hardware;
                self.sync_active_run_record();
            }
            Message::ApplyHardwareOptimizationPlan => {
                let s = self.optimization_plan.summary.clone();
                self.cfg.hyper.compute_threads = s.recommended_threads;
                self.cfg.hyper.batch_size = s.recommended_batch_size;
                self.cfg.hyper.grad_accum_steps = s.recommended_grad_accum;
                self.cfg.hardware_exec.precision = s.recommended_precision;
                self.cfg.hardware_exec.activation_checkpointing =
                    s.recommended_activation_checkpointing;
                self.cfg.hardware_exec.fused_ce_chunk_tokens = s.recommended_fused_ce_chunk;
                self.cfg.tokenizer.pad_to_multiple = if s.resolved_target == ComputeTarget::Gpu {
                    128
                } else {
                    64
                };
                self.cfg.tokenizer.vocab_size = s.recommended_vocab_size;
                self.vocab_input = s.recommended_vocab_size.to_string();
                self.sync_active_run_record();
                let msg = format!(
                    "Applied custom plan: {} · micro-batch={} × accum={} ({} tok/step), threads={}, vocab={}.",
                    s.resolved_device_label,
                    s.recommended_batch_size,
                    s.recommended_grad_accum,
                    s.effective_tokens_per_step,
                    s.recommended_threads,
                    s.recommended_vocab_size
                );
                self.log_event("opt-plan", &msg);
                self.banner = Some((true, msg));
            }
            Message::ExportOptimizationScript => {
                let run_dir = self.active_run_dir();
                let _ = std::fs::create_dir_all(&run_dir);
                let out_path = run_dir.join("optimization_plan.toml");
                match std::fs::write(&out_path, &self.optimization_plan.custom_script_toml) {
                    Ok(()) => {
                        let msg = format!(
                            "Exported custom hardware optimization script -> {}",
                            out_path.display()
                        );
                        self.log_event("export-plan", &msg);
                        self.banner = Some((true, msg));
                    }
                    Err(e) => {
                        self.banner = Some((false, format!("Could not write plan file: {e}")));
                    }
                }
            }
            Message::RunComputeBenchmark => {
                let rep = run_live_compute_benchmark(
                    &self.hardware,
                    self.cfg.hardware_exec.preferred_gpu_index,
                    self.cfg.hyper.compute_threads,
                    256,
                );
                let msg = format!(
                    "SGEMM 256×256 Benchmark — Winner: {} ({})",
                    rep.recommended_winner, rep.note
                );
                self.compute_benchmark = Some(rep);
                self.log_event("benchmark", &msg);
                self.banner = Some((true, msg));
            }

            // Stage 05: Seed Hierarchy, Provenance & Genesis Random State Lab
            Message::SelectPrngAlgorithm(algo) => {
                self.cfg.seeds.algorithm = algo;
                self.cfg.model.prng_algorithm = algo;
                self.genesis_report = build_and_inspect_genesis(&self.cfg).ok().map(|(_, r)| r);
                self.sync_active_run_record();
            }
            Message::ToggleLockSubsystemsToMaster => {
                self.cfg.seeds.lock_subsystems_to_master =
                    !self.cfg.seeds.lock_subsystems_to_master;
                if self.cfg.seeds.lock_subsystems_to_master {
                    self.cfg.seeds.master_seed = self.cfg.hyper.master_seed;
                    self.cfg.seeds.sync_from_master();
                }
                self.cfg.model.init_seed = self.cfg.seeds.effective_weight_seed();
                self.sync_text_inputs();
                self.genesis_report = build_and_inspect_genesis(&self.cfg).ok().map(|(_, r)| r);
                self.sync_active_run_record();
            }
            Message::EditWeightSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.seeds.lock_subsystems_to_master = false;
                    self.cfg.seeds.weight_init_seed = v;
                    self.cfg.model.init_seed = v;
                    self.sync_active_run_record();
                }
                self.weight_seed_input = s;
            }
            Message::EditDataSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.seeds.lock_subsystems_to_master = false;
                    self.cfg.seeds.data_order_seed = v;
                    self.sync_active_run_record();
                }
                self.data_seed_input = s;
            }
            Message::EditStochasticSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.seeds.lock_subsystems_to_master = false;
                    self.cfg.seeds.stochastic_seed = v;
                    self.sync_active_run_record();
                }
                self.stochastic_seed_input = s;
            }
            Message::ToggleAutoExportGenesis => {
                self.cfg.seeds.auto_export_genesis_init =
                    !self.cfg.seeds.auto_export_genesis_init;
                self.sync_active_run_record();
            }
            Message::EditGenesisReloadPath(v) => {
                self.cfg.seeds.genesis_reload_path = v;
                self.sync_active_run_record();
            }
            Message::InspectGenesisNow => match build_and_inspect_genesis(&self.cfg) {
                Ok((_, rep)) => {
                    let msg = format!(
                        "Inspected step-0 initial state: SHA-256 {}… ({} tensors, std={:.4}).",
                        &rep.sha256_hex[..16],
                        rep.total_tensors,
                        rep.global_std
                    );
                    self.genesis_report = Some(rep);
                    self.log_event("genesis", &msg);
                    self.banner = Some((true, msg));
                }
                Err(err) => {
                    self.banner = Some((false, err));
                }
            },
            Message::ExportProvenanceBundle {
                include_genesis_weights,
            } => {
                let out_dir = self.active_run_dir().join("exports");
                let train_docs = self
                    .dataset
                    .as_ref()
                    .map(|d| d.train_docs.len())
                    .unwrap_or(0);
                let val_docs = self.dataset.as_ref().map(|d| d.val_docs.len()).unwrap_or(0);
                let completed = self.active_run().map(|r| r.completed_steps).unwrap_or(0);
                let best = self.active_run().and_then(|r| r.best_loss);

                match export_provenance_and_genesis(
                    &self.cfg,
                    &self.hardware,
                    &self.optimization_plan,
                    self.tokenizer.as_ref(),
                    train_docs,
                    val_docs,
                    completed,
                    best,
                    &out_dir,
                    include_genesis_weights,
                ) {
                    Ok(rep) => {
                        let msg = if include_genesis_weights {
                            format!(
                                "Exported settings + hardware provenance + initial random state `genesis_step0.safetensors` -> {}",
                                out_dir.display()
                            )
                        } else {
                            format!(
                                "Exported settings + hardware provenance (`run_provenance.json` + `optimization_plan.toml`) -> {}",
                                out_dir.display()
                            )
                        };
                        self.genesis_report = Some(rep);
                        self.log_event("export-repro", &msg);
                        self.banner = Some((true, msg));
                    }
                    Err(err) => {
                        self.banner = Some((false, err));
                    }
                }
            }

            // Stage 06: Training execution
            Message::StartTraining => {
                if self.training_busy {
                    return Task::none();
                }
                if self.dataset.is_none() {
                    match load_local_or_builtin(&self.cfg.dataset) {
                        Ok(ds) => self.dataset = Some(ds),
                        Err(err) => {
                            self.banner = Some((false, err));
                            return Task::none();
                        }
                    }
                }
                let Some(dataset) = self.dataset.clone() else {
                    self.banner = Some((false, "Load or fetch a dataset first.".into()));
                    return Task::none();
                };
                let tokenizer = match &self.tokenizer {
                    Some(tk) => tk.clone(),
                    None => {
                        match LabTokenizer::train_or_load(&self.cfg.tokenizer, &dataset.train_docs)
                        {
                            Ok(tk) => {
                                self.tokenizer = Some(tk.clone());
                                tk
                            }
                            Err(err) => {
                                self.banner = Some((false, err));
                                return Task::none();
                            }
                        }
                    }
                };

                self.cfg.model.vocab_size = tokenizer.vocab_size();
                self.sync_active_run_record();

                self.history.clear();
                self.training_busy = true;
                self.training_paused = false;
                self.surface = Surface::Pipeline;
                self.stage = PipelineStage::Train;

                let control = TrainControl::new(self.telemetry_mode, self.inspected_layer);
                self.train_control = Some(control.clone());
                let run_cfg = self.cfg.clone();
                let run_dir = self.active_run_dir();

                self.log_event(
                    "train-start",
                    format!(
                        "Started {} ({}, {} layers, PRNG={}, seed={}, target={})",
                        run_cfg.name,
                        run_cfg.model.routing.label(),
                        run_cfg.model.n_layers,
                        run_cfg.seeds.algorithm.label(),
                        run_cfg.hyper.master_seed,
                        self.optimization_plan.summary.resolved_device_label
                    ),
                );

                let task = Task::sip(
                    sipper(async move |mut sender| {
                        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<TrainEvent>();
                        let worker = tokio::task::spawn_blocking(move || {
                            execute_training_pipeline(
                                run_cfg,
                                dataset,
                                tokenizer,
                                run_dir,
                                control,
                                move |ev| {
                                    let _ = tx.send(ev);
                                },
                            )
                        });
                        while let Some(ev) = rx.recv().await {
                            sender.send(ev).await;
                        }
                        match worker.await {
                            Ok(res) => res,
                            Err(e) => Err(format!("Training thread panicked: {e}")),
                        }
                    }),
                    Message::TrainProgress,
                    Message::TrainDone,
                );
                let (task, handle) = task.abortable();
                self.train_handle = Some(handle);
                return task;
            }
            Message::TogglePauseTraining => {
                if let Some(ctrl) = &self.train_control {
                    self.training_paused = !self.training_paused;
                    ctrl.paused.store(self.training_paused, Ordering::Relaxed);
                    let status = if self.training_paused {
                        "Paused training run."
                    } else {
                        "Resumed training run."
                    };
                    self.log_event("train", status);
                }
            }
            Message::RequestCheckpointSave => {
                if let Some(ctrl) = &self.train_control {
                    ctrl.save_now.store(true, Ordering::Relaxed);
                    self.banner = Some((
                        true,
                        "Queued checkpoint write at the end of the current step.".into(),
                    ));
                }
            }
            Message::StopTraining => {
                if let Some(ctrl) = &self.train_control {
                    ctrl.stop.store(true, Ordering::Relaxed);
                    ctrl.paused.store(false, Ordering::Relaxed);
                }
            }
            Message::ToggleLossLogScale => {
                self.log_loss_chart = !self.log_loss_chart;
                self.persist_settings();
            }
            Message::TrainProgress(ev) => match ev {
                TrainEvent::Started {
                    vocab_size,
                    train_windows,
                    val_windows,
                    ..
                } => {
                    self.banner = Some((
                        true,
                        format!(
                            "Training running · vocab {vocab_size}, {train_windows} train / {val_windows} val windows."
                        ),
                    ));
                }
                TrainEvent::Step { point, neural } => {
                    self.history.push(point);
                    if let Some(snap) = neural {
                        self.latest_neural = Some(snap);
                    }
                    if let Some(run) = self.runs.iter_mut().find(|r| r.id == self.active_run_id) {
                        run.completed_steps = point.step;
                        let candidate = point.val_loss.unwrap_or(point.train_loss);
                        if candidate.is_finite() && run.best_loss.is_none_or(|b| candidate < b) {
                            run.best_loss = Some(candidate);
                        }
                    }
                }
                TrainEvent::Checkpoint {
                    tag,
                    step,
                    loss,
                    path,
                } => {
                    self.refresh_checkpoint_flags();
                    self.log_event(
                        "checkpoint",
                        format!(
                            "Saved `{tag}` state at step {step} (loss {loss:.4}) -> {}",
                            path.display()
                        ),
                    );
                }
                TrainEvent::Journal(note) => {
                    self.log_event("runtime", note);
                }
                TrainEvent::Finished {
                    final_step,
                    best_loss,
                    stopped_early,
                    ..
                } => {
                    self.refresh_checkpoint_flags();
                    self.persist_runs();
                    let label = if stopped_early { "Stopped" } else { "Completed" };
                    let msg = format!(
                        "{label} at step {final_step} · best loss {:.4}. Provenance & checkpoints archived; open Playground to chat.",
                        best_loss
                    );
                    self.log_event("train-done", &msg);
                    self.banner = Some((true, msg));
                }
            },
            Message::TrainDone(res) => {
                self.training_busy = false;
                self.training_paused = false;
                self.train_control = None;
                self.train_handle = None;
                self.refresh_checkpoint_flags();
                self.persist_runs();
                if let Err(err) = res {
                    self.log_event("train-error", &err);
                    self.banner = Some((false, err));
                }
            }

            // Neural Live View
            Message::SelectTelemetryMode(mode) => {
                self.telemetry_mode = mode;
                if let Some(ctrl) = &self.train_control {
                    ctrl.telemetry_mode.store(mode as u8, Ordering::Relaxed);
                }
            }
            Message::SelectInspectedLayer(layer) => {
                self.inspected_layer = layer.min(self.cfg.model.n_layers.saturating_sub(1));
                if let Some(ctrl) = &self.train_control {
                    ctrl.inspected_layer
                        .store(self.inspected_layer, Ordering::Relaxed);
                    ctrl.snapshot_now.store(true, Ordering::Relaxed);
                }
            }
            Message::CaptureNeuralSnapshotNow => {
                if let Some(ctrl) = &self.train_control {
                    ctrl.snapshot_now.store(true, Ordering::Relaxed);
                    self.banner = Some((true, "Requested live neural snapshot on next step.".into()));
                } else {
                    let ckpt_dir = self.active_run_dir().join(self.playground_ckpt.folder());
                    let fallback_dir = self.active_run_dir().join("best");
                    let target = if ckpt_dir.join("model.safetensors").is_file() {
                        ckpt_dir
                    } else {
                        fallback_dir
                    };
                    if let Ok(model) = crate::transformer::TransformerModel::load_checkpoint(
                        &target,
                        candle_core::Device::Cpu,
                    ) {
                        let snap = crate::telemetry::capture_neural_snapshot(
                            &model.varmap,
                            None,
                            model.cfg.n_layers,
                            self.inspected_layer,
                            &[],
                            self.active_run().map(|r| r.completed_steps).unwrap_or(0),
                        );
                        self.latest_neural = Some(snap);
                        self.banner = Some((
                            true,
                            "Loaded neural weight snapshot from saved `.safetensors` checkpoint."
                                .into(),
                        ));
                    } else {
                        self.banner = Some((
                            false,
                            "Start training or save a checkpoint first to inspect weights.".into(),
                        ));
                    }
                }
            }

            // Playground
            Message::SelectPlaygroundCheckpoint(choice) => self.playground_ckpt = choice,
            Message::ToggleAbCompare => {
                self.cfg.sampling.ab_compare = !self.cfg.sampling.ab_compare;
                self.sync_active_run_record();
            }
            Message::EditPlaygroundPrompt(v) => self.playground_input = v,
            Message::ClearPlaygroundChat => {
                self.playground_turns.clear();
                self.streaming_primary.clear();
                self.streaming_secondary.clear();
            }
            Message::AdjustTemperature(delta) => {
                self.cfg.sampling.temperature =
                    (self.cfg.sampling.temperature + delta).clamp(0.0, 2.0);
                self.sync_active_run_record();
            }
            Message::AdjustTopP(delta) => {
                self.cfg.sampling.top_p = (self.cfg.sampling.top_p + delta).clamp(0.1, 1.0);
                self.sync_active_run_record();
            }
            Message::AdjustSampleTopK(delta) => {
                self.cfg.sampling.top_k =
                    (self.cfg.sampling.top_k as isize + delta).clamp(0, 200) as usize;
                self.sync_active_run_record();
            }
            Message::AdjustRepPenalty(delta) => {
                self.cfg.sampling.repetition_penalty =
                    (self.cfg.sampling.repetition_penalty + delta).clamp(1.0, 1.5);
                self.sync_active_run_record();
            }
            Message::AdjustMaxNewTokens(delta) => {
                self.cfg.sampling.max_new_tokens =
                    (self.cfg.sampling.max_new_tokens as isize + delta).clamp(8, 512) as usize;
                self.sync_active_run_record();
            }
            Message::EditSampleSeed(s) => {
                if let Ok(v) = s.trim().parse::<u64>() {
                    self.cfg.sampling.seed = v;
                    self.sync_active_run_record();
                }
                self.sample_seed_input = s;
            }
            Message::SendPlaygroundPrompt => {
                let prompt = self.playground_input.trim().to_owned();
                if prompt.is_empty() || self.generating {
                    return Task::none();
                }
                let run_dir = self.active_run_dir();
                let primary_dir = if self.cfg.sampling.ab_compare {
                    run_dir.join("best")
                } else {
                    let wanted = run_dir.join(self.playground_ckpt.folder());
                    if wanted.join("model.safetensors").is_file() {
                        wanted
                    } else {
                        run_dir.join("best")
                    }
                };
                if !primary_dir.join("model.safetensors").is_file() {
                    self.banner = Some((
                        false,
                        "No trained `.safetensors` checkpoint found for this run yet—train for a few steps first.".into(),
                    ));
                    return Task::none();
                }
                let secondary_dir = if self.cfg.sampling.ab_compare
                    && run_dir.join("latest/model.safetensors").is_file()
                {
                    Some(run_dir.join("latest"))
                } else {
                    None
                };

                let prior_turns: Vec<(String, String)> = self
                    .playground_turns
                    .iter()
                    .flat_map(|t| {
                        vec![
                            ("user".to_owned(), t.user.clone()),
                            ("assistant".to_owned(), t.reply_primary.clone()),
                        ]
                    })
                    .collect();

                self.playground_turns.push(PlaygroundTurn {
                    user: prompt.clone(),
                    reply_primary: String::new(),
                    reply_secondary: secondary_dir.as_ref().map(|_| String::new()),
                });
                self.playground_input.clear();
                self.streaming_primary.clear();
                self.streaming_secondary.clear();
                self.generating = true;
                self.gen_stop = Arc::new(AtomicBool::new(false));
                let stop_flag = self.gen_stop.clone();
                let sampling = self.cfg.sampling.clone();

                let task = Task::sip(
                    sipper(async move |mut sender| {
                        let (tx, mut rx) =
                            tokio::sync::mpsc::unbounded_channel::<GenerationEvent>();
                        let worker = tokio::task::spawn_blocking(move || -> Result<(), String> {
                            let tx1 = tx.clone();
                            let _ = generate_from_checkpoint(
                                &primary_dir,
                                &prior_turns,
                                &prompt,
                                &sampling,
                                0,
                                &stop_flag,
                                move |ev| {
                                    let _ = tx1.send(ev);
                                },
                            )?;
                            if let Some(sec_dir) = secondary_dir {
                                if !stop_flag.load(Ordering::Relaxed) {
                                    let _ = generate_from_checkpoint(
                                        &sec_dir,
                                        &prior_turns,
                                        &prompt,
                                        &sampling,
                                        1,
                                        &stop_flag,
                                        move |ev| {
                                            let _ = tx.send(ev);
                                        },
                                    )?;
                                }
                            }
                            Ok(())
                        });
                        while let Some(ev) = rx.recv().await {
                            sender.send(ev).await;
                        }
                        match worker.await {
                            Ok(res) => res,
                            Err(e) => Err(format!("Inference worker panicked: {e}")),
                        }
                    }),
                    Message::GenerationProgress,
                    Message::GenerationDone,
                );
                let (task, handle) = task.abortable();
                self.gen_handle = Some(handle);
                return task;
            }
            Message::StopGeneration => {
                self.gen_stop.store(true, Ordering::Relaxed);
            }
            Message::GenerationProgress(ev) => match ev {
                GenerationEvent::Token {
                    slot, text_so_far, ..
                } => {
                    if let Some(last) = self.playground_turns.last_mut() {
                        if slot == 0 {
                            last.reply_primary = text_so_far;
                        } else {
                            last.reply_secondary = Some(text_so_far);
                        }
                    }
                }
                GenerationEvent::Done {
                    slot,
                    full_text,
                    tok_per_sec,
                    ..
                } => {
                    self.last_gen_tps = Some(tok_per_sec);
                    if let Some(last) = self.playground_turns.last_mut() {
                        let shown = if full_text.is_empty() {
                            "[end of sequence]".to_owned()
                        } else {
                            full_text
                        };
                        if slot == 0 {
                            last.reply_primary = shown;
                        } else {
                            last.reply_secondary = Some(shown);
                        }
                    }
                }
            },
            Message::GenerationDone(res) => {
                self.generating = false;
                self.gen_handle = None;
                if let Err(err) = res {
                    self.banner = Some((false, err));
                }
            }

            // Settings & OS Vault
            Message::AdjustComputeThreads(delta) => {
                let next = (self.cfg.hyper.compute_threads as isize + delta).clamp(1, 32) as usize;
                self.cfg.hyper.compute_threads = next;
                self.persist_settings();
                self.sync_active_run_record();
            }
            Message::EditHfSecretInput(v) => self.hf_secret_draft = v,
            Message::SaveHfSecretToVault => {
                let secret = Zeroizing::new(self.hf_secret_draft.0.trim().to_owned());
                self.hf_secret_draft = RedactedInput::default();
                match Vault::os().add(Provider::Custom, secret) {
                    Ok(slot_id) => {
                        if let Some(old) = self.hf_vault_slot.replace(slot_id) {
                            let _ = Vault::os().remove(Provider::Custom, old);
                        }
                        self.persist_settings();
                        self.log_event(
                            "vault",
                            format!("Stored Hugging Face credential in OS vault (slot #{slot_id})."),
                        );
                        self.banner = Some((
                            true,
                            format!("Saved Hugging Face credential in OS vault (slot #{slot_id})."),
                        ));
                    }
                    Err(err) => {
                        self.banner = Some((false, err.message().to_owned()));
                    }
                }
            }
            Message::ClearHfSecretFromVault => {
                if let Some(slot_id) = self.hf_vault_slot.take() {
                    let _ = Vault::os().remove(Provider::Custom, slot_id);
                    self.persist_settings();
                    self.banner = Some((true, "Removed Hugging Face credential reference.".into()));
                }
            }
            Message::EditKaggleSecretInput(v) => self.kaggle_secret_draft = v,
            Message::SaveKaggleSecretToVault => {
                let secret = Zeroizing::new(self.kaggle_secret_draft.0.trim().to_owned());
                self.kaggle_secret_draft = RedactedInput::default();
                match Vault::os().add(Provider::Custom, secret) {
                    Ok(slot_id) => {
                        if let Some(old) = self.kaggle_vault_slot.replace(slot_id) {
                            let _ = Vault::os().remove(Provider::Custom, old);
                        }
                        self.persist_settings();
                        self.log_event(
                            "vault",
                            format!("Stored Kaggle credential in OS vault (slot #{slot_id})."),
                        );
                        self.banner = Some((
                            true,
                            format!("Saved Kaggle credential in OS vault (slot #{slot_id})."),
                        ));
                    }
                    Err(err) => {
                        self.banner = Some((false, err.message().to_owned()));
                    }
                }
            }
            Message::ClearKaggleSecretFromVault => {
                if let Some(slot_id) = self.kaggle_vault_slot.take() {
                    let _ = Vault::os().remove(Provider::Custom, slot_id);
                    self.persist_settings();
                    self.banner = Some((true, "Removed Kaggle credential reference.".into()));
                }
            }
            Message::WipeArea(area) => {
                if self.training_busy {
                    self.banner = Some((
                        false,
                        "Stop active training before wiping local Training storage.".into(),
                    ));
                    return Task::none();
                }
                match area {
                    AREA_RUNS => {
                        let _ = storage::wipe_app(APP_ID, AREA_RUNS);
                        if let Some(app_root) = storage::app_dir(APP_ID) {
                            let _ = std::fs::remove_dir_all(app_root.join("checkpoints"));
                        }
                        self.runs.clear();
                        let fresh = RunConfig::default();
                        self.runs.push(SavedRun {
                            id: 1,
                            slug: "run-01-tiny-transformer".to_owned(),
                            config: fresh.clone(),
                            completed_steps: 0,
                            best_loss: None,
                            has_best_ckpt: false,
                            has_latest_ckpt: false,
                            updated_secs: storage::now_secs(),
                        });
                        self.active_run_id = 1;
                        self.next_run_id = 2;
                        self.cfg = fresh;
                        self.history.clear();
                        self.latest_neural = None;
                        self.playground_turns.clear();
                        self.sync_text_inputs();
                        self.recompute_plan();
                        self.banner = Some((
                            true,
                            "Wiped Model Training runs and `.safetensors` checkpoints. OS vault keys and Archx Agent data were left untouched.".into(),
                        ));
                    }
                    AREA_SETTINGS => {
                        let _ = storage::wipe_app(APP_ID, AREA_SETTINGS);
                        self.log_loss_chart = false;
                        self.banner = Some((
                            true,
                            "Wiped Model Training preferences. OS vault keys, saved runs, and Archx Agent data were left untouched.".into(),
                        ));
                    }
                    AREA_JOURNAL => {
                        let _ = storage::wipe_app(APP_ID, AREA_JOURNAL);
                        self.journal.clear();
                        self.banner = Some((
                            true,
                            "Wiped Model Training run journal. OS vault keys, checkpoints, and Archx Agent data were left untouched.".into(),
                        ));
                    }
                    _ => {}
                }
            }
        }
        Task::none()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persisted_documents_pass_credential_guard_and_never_touch_agent_files() {
        let dir = std::env::temp_dir().join(format!("archx-training-persist-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        storage::set_thread_directory(Some(dir.clone()));

        storage::save(storage::Area::Settings, json!({"agent_marker": true})).expect("agent save");

        let mut app = App::new(None);
        app.snapshot_mode = false;
        let _ = app.update(Message::EditRunName("moe-experiment".into()));
        let _ = app.update(Message::SelectRouting(Routing::MoE));
        let _ = app.update(Message::SelectComputeTarget(ComputeTarget::Cpu));
        let _ = app.update(Message::SelectPrngAlgorithm(PrngAlgorithm::Pcg64Dxsm));
        let _ = app.update(Message::ApplyHardwareOptimizationPlan);
        let _ = app.update(Message::RunTokenizerArena);
        let _ = app.update(Message::ExportProvenanceBundle {
            include_genesis_weights: true,
        });
        let _ = app.update(Message::ToggleLossLogScale);
        app.log_event("test", "verified app-scoped storage");

        assert!(storage::load_app_body(APP_ID, AREA_RUNS).is_some());
        assert!(storage::load_app_body(APP_ID, AREA_SETTINGS).is_some());
        assert!(storage::load_app_body(APP_ID, AREA_JOURNAL).is_some());
        assert_eq!(
            storage::load_body(storage::Area::Settings),
            Some(json!({"agent_marker": true})),
            "Agent settings must remain untouched"
        );
        assert_eq!(app.tokenizer_arena.len(), 4);
        assert!(app.genesis_report.is_some());

        let reloaded = App::new(None);
        assert_eq!(reloaded.cfg.name, "moe-experiment");
        assert_eq!(reloaded.cfg.model.routing, Routing::MoE);
        assert_eq!(reloaded.cfg.seeds.algorithm, PrngAlgorithm::Pcg64Dxsm);
        assert!(reloaded.log_loss_chart);

        let mut reloaded = reloaded;
        let _ = reloaded.update(Message::WipeArea(AREA_RUNS));
        assert_eq!(
            storage::load_body(storage::Area::Settings),
            Some(json!({"agent_marker": true}))
        );

        storage::set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn host_contract_hooks_map_surfaces_and_back_to_launcher() {
        let dir = std::env::temp_dir().join(format!("archx-training-host-{}", std::process::id()));
        storage::set_thread_directory(Some(dir.clone()));

        let mut app = App::new(None);
        app.snapshot_mode = false;
        app.enter_surface("settings");
        assert_eq!(app.surface, Surface::Settings);
        app.enter_surface("debug");
        assert_eq!(app.surface, Surface::Journal);
        app.enter_surface("hardware");
        assert_eq!(app.stage, PipelineStage::Hardware);
        app.enter_surface("repro");
        assert_eq!(app.stage, PipelineStage::Repro);
        app.enter_surface("home");
        assert_eq!(app.surface, Surface::Pipeline);

        let _ = app.update(Message::BackToLauncher);
        assert!(app.left_for_launcher);

        app.prepare_snapshot("home");
        assert_eq!(app.history.len(), 4);

        storage::set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn manifest_satisfies_archx_shared_ready_and_file_contract() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let app = archx_shared::apps::find_any(APP_ID).expect("training manifest discovered");
        assert!(app.ready);
        assert!(app.is_live());
        assert!(app.has_code());
        assert!(
            app.contract_problems().is_empty(),
            "contract problems: {:?}",
            app.contract_problems()
        );
        assert!(
            app.verify_files(&manifest_dir).is_empty(),
            "file verification problems: {:?}",
            app.verify_files(&manifest_dir)
        );
    }
}
