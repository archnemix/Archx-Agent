//! Purpose: Renders the native Iced surfaces for Model Training (`Pipeline`, `Neural live view`, `Playground`, `Settings`, `Run journal`) using `archx_shared::style`.

use std::sync::LazyLock;

use iced::widget::{
    button, column, container, image, row, scrollable, space, svg, text, text_input,
};
use iced::{Center, Color, ContentFit, Element, Fill, FillPortion};
use zeroize::Zeroizing;

use archx_shared::{storage, style};

use crate::app::{
    APP_ID, AREA_JOURNAL, AREA_RUNS, AREA_SETTINGS, App, CheckpointChoice, Message, PipelineStage,
    RedactedInput, Surface,
};
use crate::charts::{
    arch_blueprint_svg, heatmap_16x16_svg, loss_chart_svg, lr_grad_chart_svg, moe_load_svg,
};
use crate::config::{
    ActivationKind, Backbone, DatasetSource, InitDist, LrSchedule, Mechanism, Modality, NormKind,
    OptimizerKind, PosEncoding, Preset, Routing, TokenizerKind, UiComplexity, format_count,
    format_flops, format_size_mb,
};
use crate::telemetry::{HealthState, TelemetryMode};

static BRAND_MARK: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(
        include_bytes!("../../../shared/assets/brand/archnemix-sidebar.png").to_vec(),
    )
});

#[derive(Clone, Copy)]
enum Glyph {
    Monitor,
    Message,
    Settings,
    House,
    Plus,
    Send,
    Stop,
    Lock,
    Info,
    Chevron,
}

fn icon(glyph: Glyph, size: u32, color: Color) -> svg::Svg<'static> {
    let bytes: &'static [u8] = match glyph {
        Glyph::Monitor => include_bytes!("../../../shared/assets/icons/monitor.svg"),
        Glyph::Message => include_bytes!("../../../shared/assets/icons/message-square.svg"),
        Glyph::Settings => include_bytes!("../../../shared/assets/icons/settings-2.svg"),
        Glyph::House => include_bytes!("../../../shared/assets/icons/house.svg"),
        Glyph::Plus => include_bytes!("../../../shared/assets/icons/plus.svg"),
        Glyph::Send => include_bytes!("../../../shared/assets/icons/send.svg"),
        Glyph::Stop => include_bytes!("../../../shared/assets/icons/stop.svg"),
        Glyph::Lock => include_bytes!("../../../shared/assets/icons/lock.svg"),
        Glyph::Info => include_bytes!("../../../shared/assets/icons/info.svg"),
        Glyph::Chevron => include_bytes!("../../../shared/assets/icons/chevron-down.svg"),
    };
    svg(svg::Handle::from_memory(bytes))
        .width(size)
        .height(size)
        .style(move |_, _| svg::Style { color: Some(color) })
}

pub fn root_view(app: &App) -> Element<'_, Message> {
    let body = match app.surface {
        Surface::Pipeline => pipeline_surface(app),
        Surface::NeuralLive => neural_surface(app),
        Surface::Playground => playground_surface(app),
        Surface::Settings => settings_surface(app),
        Surface::Journal => journal_surface(app),
    };

    row![left_rail(app), container(body).width(Fill).height(Fill).style(style::canvas)]
        .width(Fill)
        .height(Fill)
        .into()
}

fn nav_row(glyph: Glyph, label: &'static str, action: Message, active: bool) -> Element<'static, Message> {
    button(
        row![
            icon(glyph, 15, if active { style::WHITE } else { style::GREY }),
            text(label)
                .size(13.5)
                .font(style::LABEL)
                .color(if active { style::WHITE } else { style::GREY })
        ]
        .spacing(8)
        .align_y(Center),
    )
    .width(Fill)
    .padding([8, 10])
    .on_press(action)
    .style(move |t, s| style::side_nav(active, t, s))
    .into()
}

fn left_rail(app: &App) -> Element<'_, Message> {
    let scale = app.display.settings.factor();
    let mut col = column![
        container(
            row![
                image(BRAND_MARK.clone())
                    .width(26)
                    .height(26)
                    .content_fit(ContentFit::Contain),
                text("Model Training")
                    .size(15)
                    .font(style::STRONG)
                    .color(style::WHITE)
            ]
            .spacing(9)
            .align_y(Center)
        )
        .padding([4, 10]),
        space().height(18),
        nav_row(
            Glyph::Monitor,
            "Training pipeline",
            Message::OpenSurface(Surface::Pipeline),
            app.surface == Surface::Pipeline
        ),
        space().height(4),
        nav_row(
            Glyph::Info,
            "Neural live view",
            Message::OpenSurface(Surface::NeuralLive),
            app.surface == Surface::NeuralLive
        ),
        space().height(4),
        nav_row(
            Glyph::Message,
            "Playground chat",
            Message::OpenSurface(Surface::Playground),
            app.surface == Surface::Playground
        ),
        space().height(4),
        nav_row(
            Glyph::Settings,
            "Settings",
            Message::OpenSurface(Surface::Settings),
            app.surface == Surface::Settings
        ),
        space().height(4),
        nav_row(
            Glyph::Chevron,
            "Run journal",
            Message::OpenSurface(Surface::Journal),
            app.surface == Surface::Journal
        ),
        space().height(4),
        nav_row(Glyph::House, "Back to launcher", Message::BackToLauncher, false),
        space().height(16),
        button(
            container(
                row![
                    icon(Glyph::Plus, 15, style::BLACK),
                    text("New model run")
                        .size(13.0 * scale)
                        .font(style::STRONG)
                        .color(style::BLACK)
                ]
                .spacing(8)
                .align_y(Center)
            )
            .center_x(Fill)
        )
        .width(Fill)
        .padding([8, 16])
        .on_press(Message::NewRun)
        .style(style::primary_button),
        space().height(20),
        container(
            row![
                text("RUNS").size(11.0 * scale).font(style::LABEL).color(style::DIM),
                text("· local").size(11.0 * scale).color(style::DIM)
            ]
            .spacing(6)
        )
        .padding([0, 10]),
        space().height(8)
    ];

    for run in app.runs.iter().rev() {
        let id = run.id;
        let selected = app.active_run_id == id;
        let short_name = if run.config.name.chars().count() > 21 {
            format!("{}…", run.config.name.chars().take(20).collect::<String>())
        } else {
            run.config.name.clone()
        };
        let status_dot_ok = run.has_best_ckpt || run.has_latest_ckpt;
        col = col
            .push(
                row![
                    button(
                        row![
                            container(space().width(6).height(6))
                                .style(move |t| style::status_dot(status_dot_ok, t)),
                            text(format!("{id:02}  {short_name}"))
                                .size(12.0 * scale)
                                .font(style::LABEL)
                                .color(if selected { style::WHITE } else { style::GREY })
                                .width(Fill)
                        ]
                        .spacing(8)
                        .align_y(Center)
                    )
                    .width(Fill)
                    .padding([8, 10])
                    .on_press(Message::SelectRun(id))
                    .style(move |t, s| style::list_row(selected, t, s)),
                    button(text("×").size(13))
                        .on_press(Message::DeleteRun(id))
                        .padding([6, 8])
                        .style(style::ghost_button)
                ]
                .spacing(2)
                .align_y(Center),
            )
            .push(space().height(4));
    }

    let status_text = if app.training_busy {
        if app.training_paused {
            "paused · CPU trainer".to_owned()
        } else {
            format!("training · {} threads", app.cfg.hyper.compute_threads)
        }
    } else {
        format!("CPU · {} threads · rust", app.cfg.hyper.compute_threads)
    };
    let active_dot = app.training_busy && !app.training_paused;

    let footer = column![
        container(space().height(1)).width(Fill).style(style::rail_divider),
        space().height(12),
        button(
            row![
                container(space().width(7).height(7)).style(move |t| style::status_dot(active_dot, t)),
                text(status_text)
                    .size(11.0 * scale)
                    .font(style::LABEL)
                    .color(style::GREY)
                    .width(Fill)
            ]
            .spacing(8)
            .align_y(Center)
        )
        .width(Fill)
        .padding([8, 10])
        .on_press(Message::OpenSurface(Surface::Settings))
        .style(style::endpoint_badge),
        space().height(8),
        row![
            icon(Glyph::Lock, 11, style::DIM),
            text("Pure Rust · OS vault")
                .size(10.0 * scale)
                .color(style::DIM)
                .width(Fill),
            text(concat!("v", env!("CARGO_PKG_VERSION")))
                .size(10.0 * scale)
                .color(style::DIM)
        ]
        .spacing(6)
        .align_y(Center)
        .padding([0, 4])
    ]
    .width(Fill);

    container(
        column![
            scrollable(col.padding([17, 10])).height(Fill).style(style::quiet_scroll),
            container(footer).padding([12, 15]).width(Fill)
        ]
        .height(Fill),
    )
    .width(260)
    .height(Fill)
    .style(style::rail)
    .into()
}

fn banner_bar(app: &App) -> Element<'_, Message> {
    let Some((ok, msg)) = &app.banner else {
        return space().height(0).into();
    };
    let ok_val = *ok;
    container(
        row![
            container(space().width(7).height(7)).style(move |t| style::status_dot(ok_val, t)),
            text(msg.clone())
                .size(12.5)
                .color(if ok_val { style::TEXT_2 } else { style::DANGER })
                .width(Fill),
            button(text("Dismiss").size(11))
                .padding([4, 9])
                .on_press(Message::DismissBanner)
                .style(style::tiny_button)
        ]
        .spacing(10)
        .align_y(Center),
    )
    .width(Fill)
    .padding([9, 14])
    .style(if ok_val { style::card } else { style::chat_error })
    .into()
}

// ---------------------------------------------------------------------------
// 1. PIPELINE SURFACE (01 DATA -> 02 TOKENIZER -> 03 ARCHITECT -> 04 HARDWARE -> 05 GENESIS -> 06 TRAIN)
// ---------------------------------------------------------------------------

fn pipeline_surface(app: &App) -> Element<'_, Message> {
    let simple = app.ui_complexity == UiComplexity::Simple;

    let mut stage_pills = row![].spacing(5).align_y(Center);
    for st in PipelineStage::ALL {
        let active = app.stage == st;
        let pill_lbl = if simple {
            match st {
                PipelineStage::Data => "1 Text",
                PipelineStage::Tokenizer => "2 Words",
                PipelineStage::Architecture => "3 Brain",
                PipelineStage::Hardware => "4 PC",
                PipelineStage::Repro => "5 Save",
                PipelineStage::Train => "6 Train",
            }
            .to_owned()
        } else {
            let short_lbl = match st {
                PipelineStage::Data => "DATA",
                PipelineStage::Tokenizer => "TOKENIZER",
                PipelineStage::Architecture => "MODEL",
                PipelineStage::Hardware => "HARDWARE",
                PipelineStage::Repro => "GENESIS",
                PipelineStage::Train => "TRAIN",
            };
            format!("{} {}", st.code(), short_lbl)
        };
        stage_pills = stage_pills.push(
            button(text(pill_lbl).size(11).font(style::LABEL))
                .padding([6, 10])
                .on_press(Message::SelectStage(st))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut ui_tier_pills = row![].spacing(3).align_y(Center);
    for tier in UiComplexity::ALL {
        let active = app.ui_complexity == tier;
        ui_tier_pills = ui_tier_pills.push(
            button(text(tier.label()).size(10.5).font(style::LABEL))
                .padding([4, 9])
                .on_press(Message::SelectUiComplexity(tier))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let action_btn: Element<'_, Message> = if app.training_busy {
        button(text("Stop run").size(12).font(style::STRONG))
            .padding([8, 14])
            .on_press(Message::StopTraining)
            .style(style::control_button)
            .into()
    } else {
        button(
            text("Train model  →")
                .size(12)
                .font(style::STRONG)
                .color(style::BLACK),
        )
        .padding([8, 14])
        .on_press(Message::StartTraining)
        .style(style::primary_button)
        .into()
    };

    let header = container(
        row![
            stage_pills,
            space().width(Fill),
            container(ui_tier_pills).padding([2, 3]).style(style::badge),
            text_input("Run name…", &app.cfg.name)
                .on_input(Message::EditRunName)
                .width(142)
                .padding([7, 9])
                .size(12)
                .style(style::composer_input),
            action_btn
        ]
        .spacing(7)
        .align_y(Center),
    )
    .width(Fill)
    .padding([12, 20])
    .style(style::settings_header);

    let stage_content = match app.stage {
        PipelineStage::Data => stage_data_view(app),
        PipelineStage::Tokenizer => crate::views_advanced::stage_tokenizer_deep_view(app),
        PipelineStage::Architecture => stage_architecture_view(app),
        PipelineStage::Hardware => crate::views_advanced::stage_hardware_view(app),
        PipelineStage::Repro => crate::views_advanced::stage_repro_view(app),
        PipelineStage::Train => stage_train_view(app),
    };

    let main_col = column![banner_bar(app), stage_content]
        .spacing(16)
        .padding([20, 24])
        .width(Fill);

    let body = row![
        scrollable(main_col).width(Fill).height(Fill).style(style::quiet_scroll),
        live_spec_sidebar(app)
    ]
    .width(Fill)
    .height(Fill);

    column![header, body].width(Fill).height(Fill).into()
}

fn live_spec_sidebar(app: &App) -> Element<'_, Message> {
    let est = app.cfg.estimate_specs();
    let sz = app.cfg.predict_sizes();
    let ratio = app.cfg.token_param_ratio(app.estimated_corpus_tokens());
    let m = app.cfg.model.sanitized();
    let simple = app.ui_complexity == UiComplexity::Simple;

    let kv_row = |label: &'static str, val: String| -> Element<'static, Message> {
        row![
            text(label).size(11.5).color(style::GREY).width(Fill),
            text(val).size(12).font(style::LABEL).color(style::WHITE)
        ]
        .align_y(Center)
        .into()
    };

    let kv_accent = |label: &'static str, val: String, ok: bool| -> Element<'static, Message> {
        row![
            text(label).size(11.5).color(style::GREY).width(Fill),
            text(val)
                .size(12)
                .font(style::STRONG)
                .color(if ok { style::OK } else { style::DANGER })
        ]
        .align_y(Center)
        .into()
    };

    let ckpt_status = match app.active_run() {
        Some(r) if r.has_best_ckpt => format!("Trained (loss {:.3})", r.best_loss.unwrap_or(0.0)),
        Some(r) if r.completed_steps > 0 => format!("{} steps", r.completed_steps),
        _ => "Ready to train".to_owned(),
    };

    let device_str = if app
        .optimization_plan
        .summary
        .resolved_device_label
        .starts_with("GPU")
    {
        "Graphics Card (GPU)".to_owned()
    } else {
        format!("CPU ({} threads)", app.cfg.hyper.compute_threads)
    };

    let content = if simple {
        column![
            text("YOUR AI SUMMARY")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            space().height(4),
            text(format!("{} Brain", app.cfg.preset.label().split(' ').next().unwrap_or("Custom")))
                .size(15.5)
                .font(style::DISPLAY)
                .color(style::WHITE),
            space().height(10),
            svg(arch_blueprint_svg(&m)).width(Fill).height(118),
            space().height(12),
            kv_row("Brain size", format!("{} params", format_count(sz.total_params))),
            kv_accent("Saved AI file", format_size_mb(sz.fp32_safetensors_mb), true),
            kv_row("Compact (16-bit)", format_size_mb(sz.fp16_bf16_mb)),
            kv_row("Memory needed", format_size_mb(sz.peak_train_ram_mb)),
            space().height(8),
            container(space().height(1)).width(Fill).style(style::rail_divider),
            space().height(8),
            text("TRAINING BALANCE")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            kv_accent(
                "Tokens / param",
                format!("{:.1}×", ratio.tokens_per_param),
                ratio.is_balanced
            ),
            kv_row("Total study tokens", format_count(ratio.scheduled_tokens)),
            kv_row("Runs on", device_str),
            kv_row("Status", ckpt_status),
            space().height(12),
            button(
                container(text("Chat with your AI  →").size(11.5).font(style::LABEL))
                    .center_x(Fill)
            )
            .width(Fill)
            .padding([8, 12])
            .on_press(Message::OpenSurface(Surface::Playground))
            .style(style::control_button)
        ]
        .spacing(6)
        .padding(18)
        .width(Fill)
    } else {
        column![
            text("LIVE MODEL & SIZE SPEC")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            space().height(4),
            text(format!("{} · {}", app.cfg.backbone.label(), m.routing.label()))
                .size(14.5)
                .font(style::DISPLAY)
                .color(style::WHITE),
            space().height(10),
            svg(arch_blueprint_svg(&m)).width(Fill).height(124),
            space().height(10),
            kv_row("Total parameters", format_count(est.total_params)),
            kv_row("Active / token", format_count(est.active_params)),
            kv_accent(
                "Token : Param",
                format!("{:.1}×", ratio.tokens_per_param),
                ratio.is_balanced
            ),
            kv_row(
                "Attention",
                format!("{} ({}Q / {}KV)", m.attention_mode_label(), m.n_heads, m.n_kv_heads)
            ),
            space().height(6),
            container(space().height(1)).width(Fill).style(style::rail_divider),
            space().height(6),
            text("PREDICTED DISK & RAM")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            kv_accent("FP32 checkpoint", format_size_mb(sz.fp32_safetensors_mb), true),
            kv_row("BF16 / INT4 est.", format!("{} / {}", format_size_mb(sz.fp16_bf16_mb), format_size_mb(sz.int4_quant_mb))),
            kv_row("Run folder disk", format_size_mb(sz.full_run_folder_mb)),
            kv_row("Peak train RAM", format_size_mb(sz.peak_train_ram_mb)),
            space().height(6),
            container(space().height(1)).width(Fill).style(style::rail_divider),
            space().height(6),
            kv_row("Compute / step", format_flops(est.flops_per_step)),
            kv_row("Target device", device_str),
            kv_row("Checkpoint", ckpt_status),
            space().height(10),
            button(
                container(text("Open Playground chat  →").size(11.5).font(style::LABEL))
                    .center_x(Fill)
            )
            .width(Fill)
            .padding([8, 12])
            .on_press(Message::OpenSurface(Surface::Playground))
            .style(style::control_button)
        ]
        .spacing(6)
        .padding(18)
        .width(Fill)
    };

    container(scrollable(content).height(Fill).style(style::quiet_scroll))
        .width(282)
        .height(Fill)
        .style(style::settings_panel)
        .into()
}

fn section_eyebrow(eyebrow: &'static str, title: &'static str, subtitle: &'static str) -> Element<'static, Message> {
    column![
        text(eyebrow).size(10.5).font(style::LABEL).color(style::DIM),
        text(title).size(23).font(style::DISPLAY).color(style::WHITE),
        text(subtitle).size(13).color(style::GREY)
    ]
    .spacing(4)
    .into()
}

fn stepper_box<'a>(
    label: &'static str,
    value: String,
    minus: Message,
    plus: Message,
) -> Element<'a, Message> {
    container(
        column![
            text(label).size(10.5).font(style::LABEL).color(style::DIM),
            row![
                button(text("−").size(13))
                    .padding([4, 10])
                    .on_press(minus)
                    .style(style::tiny_button),
                container(
                    text(value)
                        .size(13.5)
                        .font(style::LABEL)
                        .color(style::WHITE)
                )
                .center_x(Fill),
                button(text("+").size(13))
                    .padding([4, 10])
                    .on_press(plus)
                    .style(style::tiny_button),
            ]
            .spacing(6)
            .align_y(Center)
        ]
        .spacing(6),
    )
    .width(FillPortion(1))
    .padding(12)
    .style(style::card)
    .into()
}

fn pill_grid<'a>(pills: Vec<Element<'a, Message>>, per_row: usize) -> Element<'a, Message> {
    let mut rows = column![].spacing(6);
    let mut current = row![].spacing(7);
    let mut count = 0usize;
    for pill in pills {
        current = current.push(pill);
        count += 1;
        if count >= per_row {
            rows = rows.push(current);
            current = row![].spacing(7);
            count = 0;
        }
    }
    if count > 0 {
        rows = rows.push(current);
    }
    rows.into()
}

fn toggle_row<'a>(label: &'static str, hint: &'static str, on: bool, msg: Message) -> Element<'a, Message> {
    row![
        column![
            text(label).size(13).font(style::LABEL).color(style::WHITE),
            text(hint).size(11.5).color(style::GREY)
        ]
        .spacing(2)
        .width(Fill),
        button(
            text(if on { "ON" } else { "OFF" })
                .size(11)
                .font(style::LABEL)
        )
        .padding([5, 13])
        .on_press(msg)
        .style(move |t, s| style::mini_toggle(on, t, s))
    ]
    .spacing(12)
    .align_y(Center)
    .into()
}

// --- Stage 01: Data ---

fn stage_data_view(app: &App) -> Element<'_, Message> {
    let ds_cfg = &app.cfg.dataset;

    if app.ui_complexity == UiComplexity::Simple {
        let mut simple_sources = row![].spacing(8);
        for (src, friendly_lbl) in [
            (DatasetSource::BuiltinTinyDialogues, "Sample Chat & Dialogues"),
            (DatasetSource::BuiltinLogicQa, "Sample Reasoning & Q&A"),
            (DatasetSource::BuiltinClassicVerse, "Sample Stories & Verse"),
            (DatasetSource::BuiltinRustCode, "Sample Code"),
            (DatasetSource::LocalPath, "My Own Text File / Folder"),
        ] {
            let active = ds_cfg.source == src;
            simple_sources = simple_sources.push(
                button(text(friendly_lbl).size(12).font(style::LABEL))
                    .padding([7, 14])
                    .on_press(Message::SelectDatasetSource(src))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }

        let local_box: Element<'_, Message> = if ds_cfg.source == DatasetSource::LocalPath {
            column![
                text("PATH TO YOUR TEXT FILE OR FOLDER (.txt, .md, .jsonl, .csv)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                text_input("Paste a file or folder path…", &ds_cfg.local_path)
                    .on_input(Message::EditLocalPath)
                    .padding([9, 12])
                    .size(13)
                    .style(style::composer_input),
            ]
            .spacing(6)
            .into()
        } else {
            space().height(0).into()
        };

        let status_card: Element<'_, Message> = if let Some(ds) = &app.dataset {
            let first_sample = ds
                .train_docs
                .first()
                .map(|s| s.as_str())
                .unwrap_or("Dataset ready.");
            container(
                column![
                    row![
                        text("ACTIVE TRAINING TEXT")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM)
                            .width(Fill),
                        text(format!(
                            "{} examples ready (~{} tokens)",
                            ds.train_docs.len() + ds.val_docs.len(),
                            format_count(app.estimated_corpus_tokens().unwrap_or(0))
                        ))
                        .size(11.5)
                        .font(style::LABEL)
                        .color(style::OK),
                    ]
                    .align_y(Center),
                    container(text(first_sample).size(12.5).color(style::TEXT_2))
                        .width(Fill)
                        .padding(12)
                        .style(style::surface),
                ]
                .spacing(9),
            )
            .width(Fill)
            .padding(18)
            .style(style::card)
            .into()
        } else {
            space().height(0).into()
        };

        return column![
            section_eyebrow(
                "STEP 1 OF 6 · TRAINING TEXT",
                "What Should Your AI Learn From?",
                "Pick an included offline starter pack to try immediately, or point to your own text files."
            ),
            container(
                column![
                    text("CHOOSE TEXT SOURCE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    simple_sources,
                    local_box,
                    row![
                        button(
                            text(if app.dataset_busy {
                                "Loading text…"
                            } else {
                                "Reload Text"
                            })
                            .size(12)
                            .font(style::LABEL)
                        )
                        .padding([8, 14])
                        .on_press_maybe((!app.dataset_busy).then_some(Message::PrepareDataset))
                        .style(style::control_button),
                        space().width(Fill),
                        button(
                            text("Next: How AI Reads Words  →")
                                .size(12.5)
                                .font(style::STRONG)
                                .color(style::BLACK)
                        )
                        .padding([9, 16])
                        .on_press(Message::SelectStage(PipelineStage::Tokenizer))
                        .style(style::primary_button),
                    ]
                    .spacing(10)
                    .align_y(Center),
                ]
                .spacing(12)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            status_card,
            row![
                text("Need Hugging Face Hub, Kaggle, custom train/val splits, or deduplication?")
                    .size(11.5)
                    .color(style::DIM)
                    .width(Fill),
                button(text("Show Normal Dataset Controls").size(11).font(style::LABEL))
                    .padding([5, 11])
                    .on_press(Message::SelectUiComplexity(UiComplexity::Standard))
                    .style(style::tiny_button),
            ]
            .align_y(Center),
        ]
        .spacing(16)
        .into();
    }

    let mut builtin_row = row![].spacing(7);
    let mut external_row = row![].spacing(7);
    for src in DatasetSource::ALL {
        let active = ds_cfg.source == src;
        let pill = button(text(src.label()).size(11.5).font(style::LABEL))
            .padding([6, 12])
            .on_press(Message::SelectDatasetSource(src))
            .style(move |t, s| style::mini_toggle(active, t, s));
        if src.is_builtin() {
            builtin_row = builtin_row.push(pill);
        } else {
            external_row = external_row.push(pill);
        }
    }

    let source_detail: Element<'_, Message> = match ds_cfg.source {
        DatasetSource::LocalPath => column![
            text("LOCAL FILE OR FOLDER (.txt, .md, .jsonl, .json, .csv)")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            text_input("/path/to/dataset.jsonl or folder…", &ds_cfg.local_path)
                .on_input(Message::EditLocalPath)
                .padding([9, 12])
                .size(13)
                .style(style::composer_input),
        ]
        .spacing(6)
        .into(),
        DatasetSource::HuggingFaceHub => column![
            text("HUGGING FACE DATASET REPOSITORY")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            row![
                text_input("owner/dataset (e.g. roneneldan/TinyStories)", &ds_cfg.hf_repo)
                    .on_input(Message::EditHfRepo)
                    .padding([9, 12])
                    .size(13)
                    .width(FillPortion(2))
                    .style(style::composer_input),
                text_input("config (default)", &ds_cfg.hf_config)
                    .on_input(Message::EditHfConfig)
                    .padding([9, 12])
                    .size(13)
                    .width(FillPortion(1))
                    .style(style::composer_input),
                text_input("split (train)", &ds_cfg.hf_split)
                    .on_input(Message::EditHfSplit)
                    .padding([9, 12])
                    .size(13)
                    .width(FillPortion(1))
                    .style(style::composer_input),
            ]
            .spacing(8),
            text(if app.hf_vault_slot.is_some() {
                "Private dataset auth: OS vault Hugging Face credential active."
            } else {
                "Public datasets work without keys; add a token in Settings -> OS Vault for gated datasets."
            })
            .size(11.5)
            .color(style::GREY)
        ]
        .spacing(6)
        .into(),
        DatasetSource::KaggleDataset => column![
            text("KAGGLE DATASET SLUG & FILE")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            row![
                text_input("owner/dataset-slug", &ds_cfg.kaggle_slug)
                    .on_input(Message::EditKaggleSlug)
                    .padding([9, 12])
                    .size(13)
                    .width(FillPortion(2))
                    .style(style::composer_input),
                text_input("train.jsonl", &ds_cfg.kaggle_file)
                    .on_input(Message::EditKaggleFile)
                    .padding([9, 12])
                    .size(13)
                    .width(FillPortion(1))
                    .style(style::composer_input),
            ]
            .spacing(8),
            text("Configure optional `username:key` in Settings -> OS Vault for gated Kaggle downloads.")
                .size(11.5)
                .color(style::GREY)
        ]
        .spacing(6)
        .into(),
        DatasetSource::CustomUrl => column![
            text("CUSTOM HTTPS DATASET URL")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            text_input("https://example.org/corpus.jsonl", &ds_cfg.custom_url)
                .on_input(Message::EditCustomUrl)
                .padding([9, 12])
                .size(13)
                .style(style::composer_input),
        ]
        .spacing(6)
        .into(),
        _ => text("Offline built-in corpus selected—zero network calls or external files needed.")
            .size(12)
            .color(style::GREY)
            .into(),
    };

    let prep_label = if app.dataset_busy {
        "Fetching dataset…"
    } else if ds_cfg.source.is_builtin() || ds_cfg.source == DatasetSource::LocalPath {
        "Load & split dataset"
    } else {
        "Fetch remote dataset"
    };

    let mut adv_block = column![
        button(
            text(if app.data_advanced_open {
                "− Hide schema & filter options"
            } else {
                "+ Schema mapping & length filters"
            })
            .size(12)
            .font(style::LABEL)
        )
        .padding([7, 12])
        .on_press(Message::ToggleDataAdvanced)
        .style(style::control_button)
    ]
    .spacing(10);

    if app.data_advanced_open {
        adv_block = adv_block.push(
            container(
                column![
                    text("SCHEMA KEYS (JSONL / JSON / CSV)")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    row![
                        column![
                            text("Text column/key").size(11).color(style::GREY),
                            text_input("text", &ds_cfg.text_field)
                                .on_input(Message::EditTextField)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Prompt key (optional)").size(11).color(style::GREY),
                            text_input("prompt", &ds_cfg.prompt_field)
                                .on_input(Message::EditPromptField)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Response key (optional)").size(11).color(style::GREY),
                            text_input("response", &ds_cfg.response_field)
                                .on_input(Message::EditResponseField)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                    ]
                    .spacing(10),
                    row![
                        column![
                            text("Min chars").size(11).color(style::GREY),
                            text_input("8", &app.min_chars_input)
                                .on_input(Message::EditMinChars)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Max chars").size(11).color(style::GREY),
                            text_input("8192", &app.max_chars_input)
                                .on_input(Message::EditMaxChars)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Max remote rows").size(11).color(style::GREY),
                            text_input("500", &app.max_rows_input)
                                .on_input(Message::EditMaxRemoteRows)
                                .padding([8, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                    ]
                    .spacing(10)
                ]
                .spacing(12),
            )
            .padding(16)
            .width(Fill)
            .style(style::card),
        );
    }

    let preview_card: Element<'_, Message> = if let Some(ds) = &app.dataset {
        let mut samples_col = column![].spacing(8);
        for (i, sample) in ds.preview_samples(3).into_iter().enumerate() {
            let clipped = if sample.chars().count() > 210 {
                format!("{}…", sample.chars().take(210).collect::<String>())
            } else {
                sample
            };
            samples_col = samples_col.push(
                container(
                    column![
                        text(format!("SAMPLE {:02}", i + 1))
                            .size(10)
                            .font(style::LABEL)
                            .color(style::DIM),
                        text(clipped).size(12.5).color(style::TEXT_2)
                    ]
                    .spacing(4),
                )
                .width(Fill)
                .padding(11)
                .style(style::surface),
            );
        }

        container(
            column![
                row![
                    text("PREPARED DATASET")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!(
                        "{} train · {} val · avg {} chars/doc (deduped {})",
                        ds.train_docs.len(),
                        ds.val_docs.len(),
                        ds.avg_chars,
                        ds.dropped_duplicates
                    ))
                    .size(11.5)
                    .color(style::OK)
                ]
                .align_y(Center),
                samples_col
            ]
            .spacing(10),
        )
        .width(Fill)
        .padding(16)
        .style(style::card)
        .into()
    } else {
        container(text("No dataset loaded yet—press Load & split dataset.").size(12.5).color(style::GREY))
            .width(Fill)
            .padding(16)
            .style(style::card)
            .into()
    };

    column![
        section_eyebrow(
            "STAGE 01 / DATASET HUB",
            "Import & Split Dataset",
            "Load local files, fetch Hugging Face / Kaggle corpora, or use an offline starter dataset."
        ),
        container(
            column![
                text("STARTER CORPORA (OFFLINE)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                builtin_row,
                space().height(4),
                text("LOCAL & REMOTE SOURCES")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                external_row,
                space().height(6),
                source_detail,
                row![
                    stepper_box(
                        "TRAIN / VAL SPLIT",
                        format!("{}% / {}%", ds_cfg.train_pct, ds_cfg.val_pct),
                        Message::AdjustTrainSplit(-5),
                        Message::AdjustTrainSplit(5)
                    ),
                    container(
                        column![
                            text("SHUFFLE SEED").size(10.5).font(style::LABEL).color(style::DIM),
                            text_input("42", &app.shuffle_seed_input)
                                .on_input(Message::EditShuffleSeed)
                                .padding([7, 10])
                                .size(13)
                                .style(style::composer_input)
                        ]
                        .spacing(6)
                    )
                    .width(FillPortion(1))
                    .padding(12)
                    .style(style::card),
                ]
                .spacing(12),
                toggle_row(
                    "Exact-hash deduplication",
                    "Drops duplicate documents before splitting so validation loss stays honest.",
                    ds_cfg.deduplicate,
                    Message::ToggleDeduplicate
                ),
                row![
                    button(text(prep_label).size(12.5).font(style::STRONG))
                        .padding([9, 16])
                        .on_press_maybe((!app.dataset_busy).then_some(Message::PrepareDataset))
                        .style(style::control_button),
                    space().width(Fill),
                    button(text("Next: 02 Tokenizer  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Tokenizer))
                        .style(style::control_button)
                ]
                .align_y(Center)
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        adv_block,
        preview_card
    ]
    .spacing(16)
    .into()
}

// --- Stage 02: Tokenizer ---

#[allow(dead_code)]
fn stage_tokenizer_view(app: &App) -> Element<'_, Message> {
    let tk_cfg = &app.cfg.tokenizer;

    let mut kind_pills = row![].spacing(7);
    for kind in TokenizerKind::ALL {
        let active = tk_cfg.kind == kind;
        kind_pills = kind_pills.push(
            button(text(kind.label()).size(11.5).font(style::LABEL))
                .padding([6, 12])
                .on_press(Message::SelectTokenizerKind(kind))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let file_row: Element<'_, Message> = if tk_cfg.kind == TokenizerKind::PretrainedFile {
        column![
            text("PRETRAINED TOKENIZER.JSON PATH")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            text_input("/path/to/tokenizer.json", &tk_cfg.pretrained_path)
                .on_input(Message::EditPretrainedTokenizerPath)
                .padding([9, 12])
                .size(13)
                .style(style::composer_input)
        ]
        .spacing(6)
        .into()
    } else {
        row![
            stepper_box(
                "TARGET VOCAB SIZE",
                tk_cfg.vocab_size.to_string(),
                Message::AdjustVocabSize(-64),
                Message::AdjustVocabSize(64)
            ),
            container(
                column![
                    text("EXACT VOCAB OVERRIDE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    text_input("512", &app.vocab_input)
                        .on_input(Message::EditVocabSize)
                        .padding([7, 10])
                        .size(13)
                        .style(style::composer_input)
                ]
                .spacing(6)
            )
            .width(FillPortion(1))
            .padding(12)
            .style(style::card)
        ]
        .spacing(12)
        .into()
    };

    let mut adv = column![
        button(
            text(if app.tokenizer_advanced_open {
                "− Hide subword merge options"
            } else {
                "+ Subword merge & normalization options"
            })
            .size(12)
            .font(style::LABEL)
        )
        .padding([7, 12])
        .on_press(Message::ToggleTokenizerAdvanced)
        .style(style::control_button)
    ]
    .spacing(10);

    if app.tokenizer_advanced_open {
        adv = adv.push(
            container(
                column![
                    stepper_box(
                        "MIN MERGE FREQUENCY",
                        tk_cfg.min_frequency.to_string(),
                        Message::AdjustMinFreq(-1),
                        Message::AdjustMinFreq(1)
                    ),
                    toggle_row(
                        "Lowercase normalization",
                        "Folds uppercase ASCII/Unicode before subword segmentation.",
                        tk_cfg.lowercase,
                        Message::ToggleLowercase
                    )
                ]
                .spacing(12),
            )
            .padding(16)
            .width(Fill)
            .style(style::card),
        );
    }

    let mut token_badges = column![].spacing(6);
    let mut current_line = row![].spacing(6);
    let mut line_chars = 0usize;
    for (id, disp) in app.tokenizer_preview.tokens.iter().take(48) {
        let label = format!("{disp}  #{id}");
        line_chars += label.chars().count() + 3;
        current_line = current_line.push(
            container(text(label).size(11).font(style::LABEL).color(style::TEXT_2))
                .padding([4, 8])
                .style(style::badge),
        );
        if line_chars > 68 {
            token_badges = token_badges.push(current_line);
            current_line = row![].spacing(6);
            line_chars = 0;
        }
    }
    if line_chars > 0 {
        token_badges = token_badges.push(current_line);
    }

    let tk_summary = app
        .tokenizer
        .as_ref()
        .map(|tk| tk.summary().to_owned())
        .unwrap_or_else(|| "Not built yet".to_owned());

    column![
        section_eyebrow(
            "STAGE 02 / NATIVE RUST TOKENIZER",
            "Build or Load Tokenizer",
            "Train Byte-Level BPE, WordPiece, Unigram, or Character vocabularies directly in Rust, or load a Hugging Face tokenizer.json."
        ),
        container(
            column![
                text("TOKENIZER ALGORITHM")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                kind_pills,
                file_row,
                toggle_row(
                    "Sequence packing",
                    "Concatenates tokenized documents with <bos>/<eos> markers so zero compute is spent on padding.",
                    tk_cfg.sequence_packing,
                    Message::ToggleSequencePacking
                ),
                toggle_row(
                    "Insert <bos> and <eos> boundary tokens",
                    "Teaches the model clean document starts and generation stopping points.",
                    tk_cfg.add_bos_eos,
                    Message::ToggleBosEos
                ),
                row![
                    button(text("Train / Rebuild Tokenizer").size(12.5).font(style::STRONG))
                        .padding([9, 16])
                        .on_press(Message::BuildTokenizer)
                        .style(style::control_button),
                    text(tk_summary).size(12).color(style::OK).width(Fill),
                    button(text("Next: 03 Architecture  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Architecture))
                        .style(style::control_button)
                ]
                .spacing(12)
                .align_y(Center)
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        adv,
        container(
            column![
                row![
                    text("LIVE TOKENIZATION TESTER · 0% COST")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!(
                        "{} tokens · {:.2} chars/token",
                        app.tokenizer_preview.tokens.len(),
                        app.tokenizer_preview.chars_per_token
                    ))
                    .size(11.5)
                    .color(style::GREY)
                ]
                .align_y(Center),
                text_input("Type text to inspect exact token splits…", &app.tokenizer_sample)
                    .on_input(Message::EditTokenizerSample)
                    .padding([9, 12])
                    .size(13)
                    .style(style::composer_input),
                token_badges
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
    ]
    .spacing(16)
    .into()
}

// --- Stage 03: Architecture, Seed & Optimizations ---

fn stage_architecture_view(app: &App) -> Element<'_, Message> {
    let m = &app.cfg.model;
    let h = &app.cfg.hyper;
    let level = app.ui_complexity;

    // --- SIMPLE MODE: Ultra-clean, plain-English Brain Size + Size Prediction + Ratio Balance ---
    if level == UiComplexity::Simple {
        let mut friendly_presets = row![].spacing(8);
        for (p, friendly_lbl) in [
            (Preset::Nano, "Nano · Instant (~15s)"),
            (Preset::Micro, "Micro · Fast (~1m)"),
            (Preset::Small, "Small · Capable"),
            (Preset::Base, "Base · Deep"),
        ] {
            let active = app.cfg.preset == p;
            friendly_presets = friendly_presets.push(
                button(text(friendly_lbl).size(12).font(style::LABEL))
                    .padding([8, 15])
                    .on_press(Message::SelectPreset(p))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }

        return column![
            section_eyebrow(
                "STEP 3 OF 6 · AI BRAIN SIZE & BALANCE",
                "How Big Should Your AI Be?",
                "Pick a brain size below. We instantly predict the saved file size, memory needed, and optimal training length."
            ),
            container(
                column![
                    text("CHOOSE AI BRAIN SIZE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    friendly_presets,
                    text(format!(
                        "Current layout: {} layers · {} width · {} context window",
                        m.n_layers, m.d_model, m.seq_len
                    ))
                    .size(12)
                    .color(style::GREY),
                ]
                .spacing(10)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            crate::views_advanced::size_and_ratio_cards(app),
            row![
                button(text("Customize Layers & Optimizer (Normal)").size(11.5).font(style::LABEL))
                    .padding([8, 13])
                    .on_press(Message::SelectUiComplexity(UiComplexity::Standard))
                    .style(style::tiny_button),
                space().width(Fill),
                button(
                    text("Next: Check Your Computer  →")
                        .size(12.5)
                        .font(style::STRONG)
                        .color(style::BLACK)
                )
                .padding([9, 16])
                .on_press(Message::SelectStage(PipelineStage::Hardware))
                .style(style::primary_button),
            ]
            .spacing(10)
            .align_y(Center),
        ]
        .spacing(16)
        .into();
    }

    let mut mod_pills = Vec::new();
    for item in Modality::ALL {
        let active = app.cfg.modality == item;
        let lbl = if item.is_live_in_slice() {
            item.label().to_owned()
        } else {
            format!("{} · soon", item.label())
        };
        mod_pills.push(
            button(text(lbl).size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectModality(item))
                .style(move |t, s| style::mini_toggle(active, t, s))
                .into(),
        );
    }

    let mut mech_pills = Vec::new();
    for item in Mechanism::ALL {
        let active = app.cfg.mechanism == item;
        let lbl = if item.is_live_in_slice() {
            item.label().to_owned()
        } else {
            format!("{} · soon", item.label())
        };
        mech_pills.push(
            button(text(lbl).size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectMechanism(item))
                .style(move |t, s| style::mini_toggle(active, t, s))
                .into(),
        );
    }

    let mut bb_pills = Vec::new();
    for item in Backbone::ALL {
        let active = app.cfg.backbone == item;
        let lbl = if item.is_live_in_slice() {
            item.label().to_owned()
        } else {
            format!("{} · soon", item.label())
        };
        bb_pills.push(
            button(text(lbl).size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectBackbone(item))
                .style(move |t, s| style::mini_toggle(active, t, s))
                .into(),
        );
    }

    let mut route_row = row![].spacing(8);
    for r in Routing::ALL {
        let active = m.routing == r;
        route_row = route_row.push(
            button(text(r.label()).size(11.5).font(style::LABEL))
                .padding([6, 14])
                .on_press(Message::SelectRouting(r))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut preset_row = row![].spacing(7);
    for p in Preset::ALL {
        let active = app.cfg.preset == p;
        preset_row = preset_row.push(
            button(text(p.label()).size(11.5).font(style::LABEL))
                .padding([6, 13])
                .on_press(Message::SelectPreset(p))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let moe_section: Element<'_, Message> = if m.routing == Routing::MoE {
        container(
            column![
                text("MIXTURE-OF-EXPERTS ROUTER")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                row![
                    stepper_box(
                        "ROUTED EXPERTS",
                        m.moe.n_experts.to_string(),
                        Message::AdjustExperts(-1),
                        Message::AdjustExperts(1)
                    ),
                    stepper_box(
                        "ACTIVE TOP-K",
                        m.moe.top_k.to_string(),
                        Message::AdjustTopK(-1),
                        Message::AdjustTopK(1)
                    ),
                    stepper_box(
                        "SHARED EXPERTS",
                        m.moe.n_shared_experts.to_string(),
                        Message::AdjustSharedExperts(-1),
                        Message::AdjustSharedExperts(1)
                    ),
                ]
                .spacing(10)
            ]
            .spacing(8),
        )
        .width(Fill)
        .padding(14)
        .style(style::surface)
        .into()
    } else {
        space().height(0).into()
    };

    let mut opt_row = row![].spacing(7);
    for opt in OptimizerKind::ALL {
        let active = h.optimizer == opt;
        opt_row = opt_row.push(
            button(text(opt.label()).size(11.5).font(style::LABEL))
                .padding([6, 13])
                .on_press(Message::SelectOptimizer(opt))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut sched_row = row![].spacing(7);
    for sc in LrSchedule::ALL {
        let active = h.lr_schedule == sc;
        sched_row = sched_row.push(
            button(text(sc.label()).size(11.5).font(style::LABEL))
                .padding([6, 12])
                .on_press(Message::SelectLrSchedule(sc))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let taxonomy_card: Element<'_, Message> = if level == UiComplexity::Expert {
        container(
            column![
                text("MODEL TAXONOMY (MODALITY × MECHANISM × BACKBONE × ROUTING)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                pill_grid(mod_pills, 5),
                pill_grid(mech_pills, 4),
                pill_grid(bb_pills, 4),
                route_row
            ]
            .spacing(9),
        )
        .width(Fill)
        .padding(16)
        .style(style::card)
        .into()
    } else {
        container(
            row![
                text("ROUTING TOPOLOGY")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM)
                    .width(Fill),
                route_row
            ]
            .align_y(Center),
        )
        .width(Fill)
        .padding(14)
        .style(style::card)
        .into()
    };

    let expert_drawers_or_hint: Element<'_, Message> = if level == UiComplexity::Expert {
        expert_drawers_view(app)
    } else {
        row![
            text("Want RoPE scaling, norm placement, soft-capping, or custom init distributions?")
                .size(11.5)
                .color(style::DIM)
                .width(Fill),
            button(text("Unlock Advanced Research Controls").size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectUiComplexity(UiComplexity::Expert))
                .style(style::tiny_button),
        ]
        .align_y(Center)
        .into()
    };

    column![
        section_eyebrow(
            "STAGE 03 / MODEL ARCHITECTURE, SIZE PREDICTOR & SCALING RATIO",
            "Configure Model Dimensions, Size & Token Ratio",
            "Tune dimensions, inspect multi-format checkpoint sizes, and balance training tokens per parameter."
        ),
        crate::views_advanced::size_and_ratio_cards(app),
        taxonomy_card,
        // Essential dimensions
        container(
            column![
                row![
                    text("SIZE PRESETS")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!("Head dim: {} · {}", m.head_dim(), m.attention_mode_label()))
                        .size(11.5)
                        .color(style::GREY)
                ]
                .align_y(Center),
                preset_row,
                row![
                    stepper_box("LAYERS", m.n_layers.to_string(), Message::AdjustLayers(-1), Message::AdjustLayers(1)),
                    stepper_box("D_MODEL", m.d_model.to_string(), Message::AdjustDModel(-1), Message::AdjustDModel(1)),
                    stepper_box("Q HEADS", m.n_heads.to_string(), Message::AdjustHeads(-1), Message::AdjustHeads(1)),
                ]
                .spacing(10),
                row![
                    stepper_box(
                        "KV HEADS (GQA/MQA)",
                        format!("{} ({})", m.n_kv_heads, m.attention_mode_label()),
                        Message::AdjustKvHeads(-1),
                        Message::AdjustKvHeads(1)
                    ),
                    stepper_box("FFN DIM (D_FF)", m.d_ff.to_string(), Message::AdjustDff(-64), Message::AdjustDff(64)),
                    stepper_box("CONTEXT (SEQ)", m.seq_len.to_string(), Message::AdjustSeqLen(-32), Message::AdjustSeqLen(32)),
                ]
                .spacing(10),
                moe_section
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Seed, Optimizer & Schedule
        container(
            column![
                text("SEED, OPTIMIZER & TRAINING BUDGET")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                opt_row,
                sched_row,
                row![
                    container(
                        column![
                            row![
                                text("MASTER SEED").size(10.5).font(style::LABEL).color(style::DIM).width(Fill),
                                button(text("Randomize").size(10.5))
                                    .padding([2, 8])
                                    .on_press(Message::RandomizeSeed)
                                    .style(style::tiny_button)
                            ]
                            .align_y(Center),
                            text_input("42", &app.seed_input)
                                .on_input(Message::EditMasterSeed)
                                .padding([7, 10])
                                .size(13)
                                .style(style::composer_input)
                        ]
                        .spacing(6)
                    )
                    .width(FillPortion(1))
                    .padding(12)
                    .style(style::surface),
                    container(
                        column![
                            text("PEAK LEARNING RATE").size(10.5).font(style::LABEL).color(style::DIM),
                            text_input("0.0030", &app.lr_input)
                                .on_input(Message::EditLearningRate)
                                .padding([7, 10])
                                .size(13)
                                .style(style::composer_input)
                        ]
                        .spacing(6)
                    )
                    .width(FillPortion(1))
                    .padding(12)
                    .style(style::surface),
                    container(
                        column![
                            text("TOTAL STEPS").size(10.5).font(style::LABEL).color(style::DIM),
                            text_input("120", &app.steps_input)
                                .on_input(Message::EditTotalSteps)
                                .padding([7, 10])
                                .size(13)
                                .style(style::composer_input)
                        ]
                        .spacing(6)
                    )
                    .width(FillPortion(1))
                    .padding(12)
                    .style(style::surface),
                ]
                .spacing(10),
                row![
                    stepper_box("MICRO BATCH", h.batch_size.to_string(), Message::AdjustBatchSize(-1), Message::AdjustBatchSize(1)),
                    stepper_box("GRAD ACCUM", format!("{}×", h.grad_accum_steps), Message::AdjustGradAccum(-1), Message::AdjustGradAccum(1)),
                    stepper_box("WARMUP STEPS", h.warmup_steps.to_string(), Message::AdjustWarmupSteps(-4), Message::AdjustWarmupSteps(4)),
                ]
                .spacing(10)
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        crate::views_advanced::transformer_advanced_card(app),
        expert_drawers_or_hint,
        row![
            space().width(Fill),
            button(text("Next: 04 Hardware & Plan  →").size(12).font(style::LABEL))
                .padding([9, 15])
                .on_press(Message::SelectStage(PipelineStage::Hardware))
                .style(style::control_button)
        ]
    ]
    .spacing(16)
    .into()
}

fn expert_drawers_view(app: &App) -> Element<'_, Message> {
    let m = &app.cfg.model;
    let h = &app.cfg.hyper;

    let mut col = column![
        row![
            button(
                text(if app.expert_attn_open {
                    "− Norms, Activations & RoPE"
                } else {
                    "+ Expert: Norms, Activations & RoPE"
                })
                .size(11.5)
                .font(style::LABEL)
            )
            .padding([7, 12])
            .on_press(Message::ToggleExpertAttnDrawer)
            .style(style::control_button),
            button(
                text(if app.expert_init_open {
                    "− Init & MoE Router"
                } else {
                    "+ Expert: Init & MoE Router"
                })
                .size(11.5)
                .font(style::LABEL)
            )
            .padding([7, 12])
            .on_press(Message::ToggleExpertInitDrawer)
            .style(style::control_button),
            button(
                text(if app.expert_stability_open {
                    "− Clipping, Decay & Guards"
                } else {
                    "+ Expert: Clipping, Decay & Guards"
                })
                .size(11.5)
                .font(style::LABEL)
            )
            .padding([7, 12])
            .on_press(Message::ToggleExpertStabilityDrawer)
            .style(style::control_button),
        ]
        .spacing(8)
    ]
    .spacing(12);

    if app.expert_attn_open {
        let mut norm_pills = row![].spacing(6);
        for nk in NormKind::ALL {
            let active = m.norm == nk;
            norm_pills = norm_pills.push(
                button(text(nk.label()).size(11.5))
                    .padding([5, 12])
                    .on_press(Message::SelectNorm(nk))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }
        let mut act_pills = row![].spacing(6);
        for ak in ActivationKind::ALL {
            let active = m.activation == ak;
            act_pills = act_pills.push(
                button(text(ak.label()).size(11.5))
                    .padding([5, 12])
                    .on_press(Message::SelectActivation(ak))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }
        let mut pos_pills = row![].spacing(6);
        for pe in PosEncoding::ALL {
            let active = m.pos_encoding == pe;
            pos_pills = pos_pills.push(
                button(text(pe.label()).size(11.5))
                    .padding([5, 12])
                    .on_press(Message::SelectPosEncoding(pe))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }

        col = col.push(
            container(
                column![
                    text("NORMS, FFN ACTIVATIONS & POSITIONAL ENCODING")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    row![text("Normalization:").size(12).color(style::GREY).width(120), norm_pills].align_y(Center),
                    row![text("Activation:").size(12).color(style::GREY).width(120), act_pills].align_y(Center),
                    row![text("Position:").size(12).color(style::GREY).width(120), pos_pills].align_y(Center),
                    row![
                        container(
                            column![
                                text("ROPE THETA (θ)").size(10.5).font(style::LABEL).color(style::DIM),
                                text_input("10000", &app.rope_theta_input)
                                    .on_input(Message::EditRopeTheta)
                                    .padding([7, 10])
                                    .size(12.5)
                                    .style(style::composer_input)
                            ]
                            .spacing(5)
                        )
                        .width(FillPortion(1))
                        .padding(12)
                        .style(style::surface),
                        stepper_box(
                            "SLIDING WINDOW (0 = FULL)",
                            if m.sliding_window == 0 { "Full".into() } else { m.sliding_window.to_string() },
                            Message::AdjustSlidingWindow(-32),
                            Message::AdjustSlidingWindow(32)
                        )
                    ]
                    .spacing(10),
                    toggle_row("QK-Norm", "Normalizes queries & keys before attention dot-products to prevent logit spikes.", m.qk_norm, Message::ToggleQkNorm),
                    toggle_row("Tie input/output embeddings", "Shares token embedding matrix with the final LM head to cut parameter RAM.", m.tie_embeddings, Message::ToggleTieEmbeddings),
                    toggle_row("Linear projection biases", "Adds learnable additive bias vectors to QKV and FFN projections.", m.use_bias, Message::ToggleUseBias),
                ]
                .spacing(10),
            )
            .width(Fill)
            .padding(16)
            .style(style::card),
        );
    }

    if app.expert_init_open {
        let mut init_pills = row![].spacing(6);
        for idist in InitDist::ALL {
            let active = m.init_dist == idist;
            init_pills = init_pills.push(
                button(text(idist.label()).size(11.5))
                    .padding([5, 12])
                    .on_press(Message::SelectInitDist(idist))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }
        col = col.push(
            container(
                column![
                    text("WEIGHT INITIALIZATION & MOE REGULARIZATION")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    init_pills,
                    row![
                        column![
                            text("Init std (σ)").size(11).color(style::GREY),
                            text_input("0.020", &app.init_std_input)
                                .on_input(Message::EditInitStd)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("MoE aux-loss α").size(11).color(style::GREY),
                            text_input("0.020", &app.aux_loss_input)
                                .on_input(Message::EditAuxLossWeight)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("MoE z-loss").size(11).color(style::GREY),
                            text_input("0.0010", &app.z_loss_input)
                                .on_input(Message::EditZLossWeight)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Router jitter").size(11).color(style::GREY),
                            text_input("0.010", &app.jitter_input)
                                .on_input(Message::EditRouterJitter)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                    ]
                    .spacing(10),
                    toggle_row(
                        "Residual depth scaling (1/√2L)",
                        "Scales Wo and Wdown projections by 1/√(2·n_layers) for stable deep signal propagation.",
                        m.residual_scale,
                        Message::ToggleResidualScale
                    )
                ]
                .spacing(10),
            )
            .width(Fill)
            .padding(16)
            .style(style::card),
        );
    }

    if app.expert_stability_open {
        col = col.push(
            container(
                column![
                    text("OPTIMIZER REGULARIZATION, STABILITY & CHECKPOINTING")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    row![
                        column![
                            text("Grad clip L2").size(11).color(style::GREY),
                            text_input("1.00", &app.grad_clip_input)
                                .on_input(Message::EditGradClip)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Weight decay").size(11).color(style::GREY),
                            text_input("0.010", &app.weight_decay_input)
                                .on_input(Message::EditWeightDecay)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                        column![
                            text("Label smoothing").size(11).color(style::GREY),
                            text_input("0.00", &app.label_smooth_input)
                                .on_input(Message::EditLabelSmoothing)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(4)
                        .width(FillPortion(1)),
                    ]
                    .spacing(10),
                    row![
                        stepper_box("EVAL EVERY", format!("{} steps", h.eval_every), Message::AdjustEvalEvery(-5), Message::AdjustEvalEvery(5)),
                        stepper_box("SAVE EVERY", format!("{} steps", h.checkpoint_every), Message::AdjustCheckpointEvery(-10), Message::AdjustCheckpointEvery(10)),
                    ]
                    .spacing(10),
                    toggle_row(
                        "Automatic NaN & loss-spike rollback",
                        "Restores last healthy weights and halves effective LR if gradients diverge.",
                        h.nan_rollback,
                        Message::ToggleNanRollback
                    )
                ]
                .spacing(10),
            )
            .width(Fill)
            .padding(16)
            .style(style::card),
        );
    }

    col.into()
}

// --- Stage 04: Train ---

fn stage_train_view(app: &App) -> Element<'_, Message> {
    let latest = app.history.last().copied();
    let cur_step = latest.map(|p| p.step).unwrap_or(0);
    let total_steps = app.cfg.hyper.total_steps.max(1);

    let metric_tile = |label: &'static str, value: String, sub: String| -> Element<'static, Message> {
        container(
            column![
                text(label).size(10).font(style::LABEL).color(style::DIM),
                text(value).size(18).font(style::DISPLAY).color(style::WHITE),
                text(sub).size(11).color(style::GREY)
            ]
            .spacing(3),
        )
        .width(FillPortion(1))
        .padding(13)
        .style(style::card)
        .into()
    };

    let controls: Element<'_, Message> = if app.training_busy {
        row![
            button(
                text(if app.training_paused { "Resume" } else { "Pause" })
                    .size(12.5)
                    .font(style::STRONG)
                    .color(style::BLACK)
            )
            .padding([8, 16])
            .on_press(Message::TogglePauseTraining)
            .style(style::primary_button),
            button(text("Save checkpoint now").size(12))
                .padding([8, 14])
                .on_press(Message::RequestCheckpointSave)
                .style(style::control_button),
            button(text("Stop").size(12))
                .padding([8, 14])
                .on_press(Message::StopTraining)
                .style(style::control_button),
            space().width(Fill),
            button(text("Inspect Neural Live View  →").size(12))
                .padding([8, 14])
                .on_press(Message::OpenSurface(Surface::NeuralLive))
                .style(style::control_button),
        ]
        .spacing(8)
        .align_y(Center)
        .into()
    } else {
        row![
            button(
                text("Start Training in Rust")
                    .size(12.5)
                    .font(style::STRONG)
                    .color(style::BLACK)
            )
            .padding([9, 18])
            .on_press(Message::StartTraining)
            .style(style::primary_button),
            space().width(Fill),
            button(text("Test in Playground  →").size(12))
                .padding([9, 15])
                .on_press(Message::OpenSurface(Surface::Playground))
                .style(style::control_button),
        ]
        .spacing(10)
        .align_y(Center)
        .into()
    };

    let best_val = app
        .active_run()
        .and_then(|r| r.best_loss)
        .map(|v| format!("best {v:.4}"))
        .unwrap_or_else(|| "awaiting step 1".into());

    column![
        section_eyebrow(
            "STAGE 06 / IN-APP EXECUTION & TELEMETRY",
            "Train & Monitor Convergence",
            "Runs multi-threaded reverse-mode autograd on your selected hardware and saves `.safetensors` checkpoints + provenance."
        ),
        container(controls).width(Fill).padding(16).style(style::card),
        row![
            metric_tile(
                "PROGRESS",
                format!("{cur_step} / {total_steps}"),
                format!("{:.0}% complete", (cur_step as f32 * 100.0 / total_steps as f32).min(100.0))
            ),
            metric_tile(
                "TRAIN LOSS",
                latest.map(|p| format!("{:.4}", p.train_loss)).unwrap_or_else(|| "—".into()),
                best_val
            ),
            metric_tile(
                "PERPLEXITY",
                latest.map(|p| format!("{:.2}", p.perplexity)).unwrap_or_else(|| "—".into()),
                latest
                    .and_then(|p| p.val_loss)
                    .map(|vl| format!("val loss {vl:.4}"))
                    .unwrap_or_else(|| "causal CE".into())
            ),
            metric_tile(
                "THROUGHPUT",
                latest.map(|p| format!("{:.0} tok/s", p.tokens_per_sec)).unwrap_or_else(|| "—".into()),
                latest.map(|p| format!("grad {:.3} · lr {:.1e}", p.grad_norm, p.lr)).unwrap_or_else(|| "idle".into())
            ),
        ]
        .spacing(10),
        container(
            column![
                row![
                    text("LOSS CURVE · TRAIN (WHITE) & VALIDATION (EMERALD)")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(
                        text(if app.log_loss_chart { "Log scale" } else { "Linear scale" })
                            .size(11)
                    )
                    .padding([4, 10])
                    .on_press(Message::ToggleLossLogScale)
                    .style(move |t, s| style::mini_toggle(app.log_loss_chart, t, s))
                ]
                .align_y(Center),
                svg(loss_chart_svg(&app.history, app.log_loss_chart))
                    .width(Fill)
                    .height(176)
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(16)
        .style(style::card),
        container(
            column![
                text("LEARNING RATE SCHEDULE (AMBER) & GRADIENT L2 NORM (SILVER)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                svg(lr_grad_chart_svg(&app.history)).width(Fill).height(118)
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(16)
        .style(style::card)
    ]
    .spacing(16)
    .into()
}

// ---------------------------------------------------------------------------
// 2. NEURAL LIVE VIEW SURFACE (ZERO-PENALTY ATOMIC TELEMETRY)
// ---------------------------------------------------------------------------

fn neural_surface(app: &App) -> Element<'_, Message> {
    let mut mode_pills = row![].spacing(7);
    for mode in TelemetryMode::ALL {
        let active = app.telemetry_mode == mode;
        mode_pills = mode_pills.push(
            button(text(mode.label()).size(11.5).font(style::LABEL))
                .padding([6, 12])
                .on_press(Message::SelectTelemetryMode(mode))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut layer_pills = Vec::new();
    for l in 0..app.cfg.model.n_layers {
        let active = app.inspected_layer == l;
        layer_pills.push(
            button(text(format!("L{l:02}")).size(11).font(style::LABEL))
                .padding([5, 10])
                .on_press(Message::SelectInspectedLayer(l))
                .style(move |t, s| style::mini_toggle(active, t, s))
                .into(),
        );
    }

    let body: Element<'_, Message> = if let Some(snap) = &app.latest_neural {
        let mut health_rows = column![
            row![
                text("GROUP").size(10.5).color(style::DIM).width(FillPortion(2)),
                text("WEIGHT L2").size(10.5).color(style::DIM).width(FillPortion(1)),
                text("GRAD L2").size(10.5).color(style::DIM).width(FillPortion(1)),
                text("STD DEV").size(10.5).color(style::DIM).width(FillPortion(1)),
                text("NEAR-ZERO").size(10.5).color(style::DIM).width(FillPortion(1)),
                text("STATE").size(10.5).color(style::DIM).width(FillPortion(1)),
            ]
        ]
        .spacing(7);

        for lh in &snap.layers {
            let state_color = match lh.state {
                HealthState::Healthy => style::OK,
                HealthState::Quiet => style::GREY,
                HealthState::Hot => style::WARN,
            };
            health_rows = health_rows.push(
                container(
                    row![
                        text(lh.label.clone()).size(12).font(style::LABEL).color(style::WHITE).width(FillPortion(2)),
                        text(format!("{:.3}", lh.weight_l2)).size(12).color(style::TEXT_2).width(FillPortion(1)),
                        text(format!("{:.4}", lh.grad_l2)).size(12).color(style::TEXT_2).width(FillPortion(1)),
                        text(format!("{:.4}", lh.std_dev)).size(12).color(style::GREY).width(FillPortion(1)),
                        text(format!("{:.1}%", lh.near_zero_pct)).size(12).color(style::GREY).width(FillPortion(1)),
                        text(lh.state.label()).size(11.5).color(state_color).width(FillPortion(1)),
                    ]
                    .align_y(Center),
                )
                .padding([7, 10])
                .style(style::surface),
            );
        }

        let moe_card: Element<'_, Message> = if !snap.expert_load_pct.is_empty() {
            container(
                column![
                    text("MOE ROUTER EXPERT UTILIZATION (%) · DASHED = IDEAL UNIFORM")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    svg(moe_load_svg(&snap.expert_load_pct)).width(Fill).height(120)
                ]
                .spacing(8),
            )
            .width(Fill)
            .padding(16)
            .style(style::card)
            .into()
        } else {
            space().height(0).into()
        };

        column![
            row![
                container(
                    column![
                        row![
                            text(format!("WEIGHT MATRIX 16×16 · {}", snap.inspected_matrix_name))
                                .size(10.5)
                                .font(style::LABEL)
                                .color(style::DIM)
                                .width(Fill),
                            text(format!("peak ±{:.4}", snap.weight_peak)).size(11).color(style::GREY)
                        ],
                        svg(heatmap_16x16_svg(&snap.weight_tile, false)).width(208).height(208)
                    ]
                    .spacing(10)
                    .align_x(Center)
                )
                .width(FillPortion(1))
                .padding(16)
                .style(style::card),
                container(
                    column![
                        row![
                            text("GRADIENT MATRIX 16×16")
                                .size(10.5)
                                .font(style::LABEL)
                                .color(style::DIM)
                                .width(Fill),
                            text(format!("peak ±{:.5}", snap.grad_peak)).size(11).color(style::GREY)
                        ],
                        svg(heatmap_16x16_svg(&snap.grad_tile, true)).width(208).height(208)
                    ]
                    .spacing(10)
                    .align_x(Center)
                )
                .width(FillPortion(1))
                .padding(16)
                .style(style::card),
            ]
            .spacing(14),
            moe_card,
            container(
                column![
                    text(format!("PER-LAYER NORM & SPARSITY HEALTH (STEP {})", snap.step))
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    health_rows
                ]
                .spacing(10)
            )
            .width(Fill)
            .padding(16)
            .style(style::card)
        ]
        .spacing(16)
        .into()
    } else {
        container(
            column![
                text("Neural sampling is Off by default so training runs at 100% raw speed.")
                    .size(14)
                    .color(style::WHITE),
                text("Choose a sampling interval above or click Capture Snapshot Now to inspect live or saved `.safetensors` weights.")
                    .size(12.5)
                    .color(style::GREY)
            ]
            .spacing(6),
        )
        .width(Fill)
        .padding(22)
        .style(style::card)
        .into()
    };

    let content = column![
        banner_bar(app),
        row![
            section_eyebrow(
                "NEURAL LIVE VIEW",
                "Weight, Gradient & Router Inspector",
                "Zero overhead when Off; downsamples 16×16 tensor slices and layer norms on demand."
            ),
            space().width(Fill),
            container(
                text(app.telemetry_mode.badge())
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::OK)
            )
            .padding([5, 11])
            .style(|t| style::tag_badge(Some(true), t)),
            button(
                text("Capture snapshot now")
                    .size(12)
                    .font(style::STRONG)
                    .color(style::BLACK)
            )
            .padding([8, 15])
            .on_press(Message::CaptureNeuralSnapshotNow)
            .style(style::primary_button)
        ]
        .spacing(12)
        .align_y(Center),
        container(
            column![
                text("SAMPLING CADENCE").size(10.5).font(style::LABEL).color(style::DIM),
                mode_pills,
                text("INSPECTED LAYER").size(10.5).font(style::LABEL).color(style::DIM),
                pill_grid(layer_pills, 10),
            ]
            .spacing(9)
        )
        .width(Fill)
        .padding(16)
        .style(style::card),
        body
    ]
    .spacing(16)
    .padding([22, 28])
    .width(Fill);

    scrollable(content).height(Fill).style(style::quiet_scroll).into()
}

// ---------------------------------------------------------------------------
// 3. PLAYGROUND SURFACE (LIVE CHAT WITH YOUR JUST-TRAINED MODEL)
// ---------------------------------------------------------------------------

fn playground_surface(app: &App) -> Element<'_, Message> {
    let s = &app.cfg.sampling;
    let has_ckpt = app
        .active_run()
        .is_some_and(|r| r.has_best_ckpt || r.has_latest_ckpt);

    let topbar = container(
        row![
            text(format!("Checkpoint · {}", app.cfg.name))
                .size(13)
                .font(style::STRONG)
                .color(style::WHITE),
            button(text(CheckpointChoice::Best.label()).size(11.5))
                .padding([5, 12])
                .on_press(Message::SelectPlaygroundCheckpoint(CheckpointChoice::Best))
                .style(move |t, st| style::mini_toggle(
                    !s.ab_compare && app.playground_ckpt == CheckpointChoice::Best,
                    t,
                    st
                )),
            button(text(CheckpointChoice::Latest.label()).size(11.5))
                .padding([5, 12])
                .on_press(Message::SelectPlaygroundCheckpoint(CheckpointChoice::Latest))
                .style(move |t, st| style::mini_toggle(
                    !s.ab_compare && app.playground_ckpt == CheckpointChoice::Latest,
                    t,
                    st
                )),
            button(text("A/B Compare (best vs latest)").size(11.5))
                .padding([5, 12])
                .on_press(Message::ToggleAbCompare)
                .style(move |t, st| style::mini_toggle(s.ab_compare, t, st)),
            space().width(Fill),
            if let Some(tps) = app.last_gen_tps {
                Element::from(text(format!("{tps:.0} tok/s")).size(11.5).color(style::DIM))
            } else {
                Element::from(space().width(0))
            },
            button(text("Clear").size(11.5))
                .padding([5, 10])
                .on_press(Message::ClearPlaygroundChat)
                .style(style::tiny_button)
        ]
        .spacing(8)
        .align_y(Center),
    )
    .width(Fill)
    .padding([12, 22])
    .style(style::settings_header);

    let stream: Element<'_, Message> = if app.playground_turns.is_empty() {
        container(
            column![
                icon(Glyph::Monitor, 28, style::GREY),
                space().height(6),
                text(if has_ckpt {
                    "Chat with your newly trained Transformer"
                } else {
                    "No checkpoint saved for this run yet"
                })
                .size(19)
                .font(style::DISPLAY)
                .color(style::WHITE),
                text(if has_ckpt {
                    "Send a prompt below to stream tokens directly from your `.safetensors` weights in pure Rust."
                } else {
                    "Run Stage 04 Train first to produce `best.safetensors`, then return here to test it live."
                })
                .size(13)
                .color(style::GREY),
                if !has_ckpt {
                    Element::from(
                        button(
                            text("Go to Stage 04 · Train  →")
                                .size(12)
                                .font(style::STRONG)
                                .color(style::BLACK),
                        )
                        .padding([8, 16])
                        .on_press(Message::OpenSurface(Surface::Pipeline))
                        .style(style::primary_button),
                    )
                } else {
                    Element::from(space().height(0))
                }
            ]
            .spacing(8)
            .align_x(Center),
        )
        .width(Fill)
        .height(Fill)
        .center_x(Fill)
        .center_y(Fill)
        .into()
    } else {
        let mut msgs = column![].spacing(14).padding([18, 28]).width(Fill);
        for turn in &app.playground_turns {
            msgs = msgs.push(
                row![
                    space().width(FillPortion(1)),
                    container(text(turn.user.clone()).size(14).color(style::WHITE))
                        .padding([10, 14])
                        .width(FillPortion(3))
                        .style(style::chat_user)
                ]
                .width(Fill),
            );

            if let Some(sec) = &turn.reply_secondary {
                msgs = msgs.push(
                    row![
                        container(
                            column![
                                text("BEST CHECKPOINT").size(10).font(style::LABEL).color(style::OK),
                                text(if turn.reply_primary.is_empty() { "…" } else { &turn.reply_primary })
                                    .size(13.5)
                                    .color(style::WHITE)
                            ]
                            .spacing(5)
                        )
                        .width(FillPortion(1))
                        .padding(14)
                        .style(style::card),
                        container(
                            column![
                                text("LATEST CHECKPOINT").size(10).font(style::LABEL).color(style::GREY),
                                text(if sec.is_empty() { "…" } else { sec })
                                    .size(13.5)
                                    .color(style::TEXT_2)
                            ]
                            .spacing(5)
                        )
                        .width(FillPortion(1))
                        .padding(14)
                        .style(style::card),
                    ]
                    .spacing(12),
                );
            } else {
                msgs = msgs.push(
                    container(
                        column![
                            text("TRAINED MODEL").size(10).font(style::LABEL).color(style::DIM),
                            text(if turn.reply_primary.is_empty() {
                                "…"
                            } else {
                                &turn.reply_primary
                            })
                            .size(14)
                            .color(style::WHITE)
                        ]
                        .spacing(5),
                    )
                    .width(Fill)
                    .padding(14)
                    .style(style::card),
                );
            }
        }
        scrollable(msgs).width(Fill).height(Fill).style(style::quiet_scroll).into()
    };

    let sampling_strip = row![
        button(text(format!("Temp {:.2} −", s.temperature)).size(11))
            .padding([4, 8])
            .on_press(Message::AdjustTemperature(-0.1))
            .style(style::tiny_button),
        button(text("+").size(11))
            .padding([4, 8])
            .on_press(Message::AdjustTemperature(0.1))
            .style(style::tiny_button),
        button(text(format!("Top-p {:.2} −", s.top_p)).size(11))
            .padding([4, 8])
            .on_press(Message::AdjustTopP(-0.05))
            .style(style::tiny_button),
        button(text("+").size(11))
            .padding([4, 8])
            .on_press(Message::AdjustTopP(0.05))
            .style(style::tiny_button),
        button(text(format!("Top-k {} −", s.top_k)).size(11))
            .padding([4, 8])
            .on_press(Message::AdjustSampleTopK(-8))
            .style(style::tiny_button),
        button(text("+").size(11))
            .padding([4, 8])
            .on_press(Message::AdjustSampleTopK(8))
            .style(style::tiny_button),
        button(text(format!("Max {} tok −", s.max_new_tokens)).size(11))
            .padding([4, 8])
            .on_press(Message::AdjustMaxNewTokens(-16))
            .style(style::tiny_button),
        button(text("+").size(11))
            .padding([4, 8])
            .on_press(Message::AdjustMaxNewTokens(16))
            .style(style::tiny_button),
        space().width(Fill),
        text("Seed:").size(11).color(style::DIM),
        text_input("42", &app.sample_seed_input)
            .on_input(Message::EditSampleSeed)
            .width(74)
            .padding([4, 8])
            .size(11.5)
            .style(style::composer_input)
    ]
    .spacing(5)
    .align_y(Center);

    let send_or_stop: Element<'_, Message> = if app.generating {
        button(icon(Glyph::Stop, 15, style::BLACK))
            .width(36)
            .height(36)
            .on_press(Message::StopGeneration)
            .style(style::chat_send)
            .into()
    } else {
        button(icon(Glyph::Send, 15, style::BLACK))
            .width(36)
            .height(36)
            .on_press(Message::SendPlaygroundPrompt)
            .style(style::chat_send)
            .into()
    };

    let composer = container(
        column![
            sampling_strip,
            row![
                text_input("Prompt your trained model…", &app.playground_input)
                    .on_input(Message::EditPlaygroundPrompt)
                    .on_submit(Message::SendPlaygroundPrompt)
                    .padding([10, 14])
                    .size(14)
                    .width(Fill)
                    .style(style::composer_input),
                send_or_stop
            ]
            .spacing(10)
            .align_y(Center)
        ]
        .spacing(9),
    )
    .width(Fill)
    .padding([12, 24])
    .style(style::chat_panel);

    column![
        topbar,
        container(banner_bar(app)).padding([8, 24]),
        stream,
        container(composer).padding([12, 24]).width(Fill)
    ]
    .width(Fill)
    .height(Fill)
    .into()
}

// ---------------------------------------------------------------------------
// 4. SETTINGS & EXPLICIT PER-AREA STORAGE WIPES
// ---------------------------------------------------------------------------

fn settings_surface(app: &App) -> Element<'_, Message> {
    let app_storage_dir = storage::app_dir(APP_ID)
        .map(|p| p.display().to_string())
        .unwrap_or_else(storage::display_path);

    let content = column![
        banner_bar(app),
        section_eyebrow(
            "MODEL TRAINING SETTINGS",
            "Compute, OS Vault & App Storage",
            "Credentials stay exclusively in the OS vault (`archx_shared::credentials`). Storage wipes affect only `apps/training/`."
        ),
        container(
            column![
                text("NATIVE RUST COMPUTE")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                stepper_box(
                    "RAYON WORKER THREADS (LEAVE 1–2 CORES FOR SMOOTH 60 FPS UI)",
                    format!("{} threads", app.cfg.hyper.compute_threads),
                    Message::AdjustComputeThreads(-1),
                    Message::AdjustComputeThreads(1)
                )
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        container(
            column![
                text("DATASET CREDENTIALS (OS SECURE VAULT ONLY)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                text("Optional tokens for gated Hugging Face or Kaggle datasets. Never written to JSON files or logs.")
                    .size(12)
                    .color(style::GREY),
                row![
                    text_input("Hugging Face token (hf_…) -> OS Vault", &app.hf_secret_draft.0)
                        .secure(true)
                        .on_input(|s| Message::EditHfSecretInput(RedactedInput(Zeroizing::new(s))))
                        .padding([8, 12])
                        .size(13)
                        .width(Fill)
                        .style(style::composer_input),
                    button(text("Store in Vault").size(12))
                        .padding([8, 14])
                        .on_press(Message::SaveHfSecretToVault)
                        .style(style::control_button),
                    if let Some(slot) = app.hf_vault_slot {
                        Element::from(
                            button(text(format!("Remove slot #{slot}")).size(11.5))
                                .padding([8, 12])
                                .on_press(Message::ClearHfSecretFromVault)
                                .style(style::tiny_button),
                        )
                    } else {
                        Element::from(text("none set").size(11.5).color(style::DIM))
                    }
                ]
                .spacing(8)
                .align_y(Center),
                row![
                    text_input("Kaggle `username:key` -> OS Vault", &app.kaggle_secret_draft.0)
                        .secure(true)
                        .on_input(|s| Message::EditKaggleSecretInput(RedactedInput(Zeroizing::new(s))))
                        .padding([8, 12])
                        .size(13)
                        .width(Fill)
                        .style(style::composer_input),
                    button(text("Store in Vault").size(12))
                        .padding([8, 14])
                        .on_press(Message::SaveKaggleSecretToVault)
                        .style(style::control_button),
                    if let Some(slot) = app.kaggle_vault_slot {
                        Element::from(
                            button(text(format!("Remove slot #{slot}")).size(11.5))
                                .padding([8, 12])
                                .on_press(Message::ClearKaggleSecretFromVault)
                                .style(style::tiny_button),
                        )
                    } else {
                        Element::from(text("none set").size(11.5).color(style::DIM))
                    }
                ]
                .spacing(8)
                .align_y(Center)
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        container(
            column![
                text("APP-SCOPED STORAGE & EXPLICIT PER-AREA WIPES")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                text(format!("Location: {app_storage_dir}"))
                    .size(12)
                    .color(style::GREY),
                text("Wiping an area removes only that Model Training data; OS vault keys and Archx Agent files are never touched.")
                    .size(11.5)
                    .color(style::DIM),
                row![
                    button(text("Wipe runs & checkpoints").size(12))
                        .padding([8, 14])
                        .on_press(Message::WipeArea(AREA_RUNS))
                        .style(style::control_button),
                    button(text("Wipe training preferences").size(12))
                        .padding([8, 14])
                        .on_press(Message::WipeArea(AREA_SETTINGS))
                        .style(style::control_button),
                    button(text("Wipe run journal").size(12))
                        .padding([8, 14])
                        .on_press(Message::WipeArea(AREA_JOURNAL))
                        .style(style::control_button),
                ]
                .spacing(10)
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
    ]
    .spacing(16)
    .padding([22, 28])
    .width(Fill);

    scrollable(content).height(Fill).style(style::quiet_scroll).into()
}

// ---------------------------------------------------------------------------
// 5. RUN JOURNAL (DEBUG SURFACE)
// ---------------------------------------------------------------------------

fn journal_surface(app: &App) -> Element<'_, Message> {
    let mut list = column![].spacing(8);
    if app.journal.is_empty() {
        list = list.push(
            container(text("No run events recorded in this session yet.").size(13).color(style::GREY))
                .width(Fill)
                .padding(18)
                .style(style::card),
        );
    } else {
        for entry in app.journal.iter().rev() {
            list = list.push(
                container(
                    row![
                        container(
                            text(entry.category.to_uppercase())
                                .size(10)
                                .font(style::LABEL)
                                .color(style::TEXT_2)
                        )
                        .padding([3, 8])
                        .style(style::badge),
                        text(entry.detail.clone())
                            .size(12.5)
                            .color(style::WHITE)
                            .width(Fill),
                        text(format!("t={}", entry.timestamp_secs))
                            .size(11)
                            .color(style::DIM)
                    ]
                    .spacing(10)
                    .align_y(Center),
                )
                .width(Fill)
                .padding([10, 14])
                .style(style::card),
            );
        }
    }

    let content = column![
        banner_bar(app),
        section_eyebrow(
            "RUN JOURNAL",
            "Audit Log & Stability Events",
            "Records dataset splits, tokenizer builds, checkpoint writes, and gradient rollback guards without secrets."
        ),
        list
    ]
    .spacing(16)
    .padding([22, 28])
    .width(Fill);

    scrollable(content).height(Fill).style(style::quiet_scroll).into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_surfaces_and_pipeline_stages_render_without_panicking() {
        let dir = std::env::temp_dir().join(format!("archx-views-test-{}", std::process::id()));
        storage::set_thread_directory(Some(dir.clone()));

        let mut app = App::new(None);
        app.prepare_snapshot("home");

        for stage in PipelineStage::ALL {
            app.surface = Surface::Pipeline;
            app.stage = stage;
            let _ = crate::home::view(&app);
        }

        for surface in [
            Surface::Pipeline,
            Surface::NeuralLive,
            Surface::Playground,
            Surface::Settings,
            Surface::Journal,
        ] {
            app.surface = surface;
            let _ = crate::home::view(&app);
        }

        storage::set_thread_directory(None);
        let _ = std::fs::remove_dir_all(dir);
    }
}
