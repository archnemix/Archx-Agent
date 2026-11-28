//! Purpose: Renders the deep Tokenizer Studio & 4-Way Comparison Arena, Hardware Inspector & Custom Optimization Planner (`04`), Seed/Genesis State & Provenance Lab (`05`), and Engine #1 Transformer advanced controls.

use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Center, Element, Fill, FillPortion};

use archx_shared::style;

use crate::app::{App, Message, PipelineStage};
use crate::config::{
    ComputeTarget, DigitPolicy, EmbedScaleMode, NormPlacement, PreTokenizeMode, PrecisionMode,
    ResidualScaleMode, RopeScalingMode, TokenizerKind, UnicodeNorm, format_count,
};
use crate::rng::PrngAlgorithm;
use crate::tokenizer::tokenizer_guide;

fn eyebrow_header(
    eyebrow: &'static str,
    title: &'static str,
    subtitle: &'static str,
) -> Element<'static, Message> {
    column![
        text(eyebrow).size(10.5).font(style::LABEL).color(style::DIM),
        text(title).size(22).font(style::DISPLAY).color(style::WHITE),
        text(subtitle).size(12.5).color(style::GREY)
    ]
    .spacing(4)
    .into()
}

fn mini_stepper<'a>(
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
                        .size(13)
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

fn switch_row<'a>(
    label: &'static str,
    hint: &'static str,
    on: bool,
    msg: Message,
) -> Element<'a, Message> {
    row![
        column![
            text(label).size(12.5).font(style::LABEL).color(style::WHITE),
            text(hint).size(11.5).color(style::GREY)
        ]
        .spacing(2)
        .width(Fill),
        button(text(if on { "ON" } else { "OFF" }).size(11).font(style::LABEL))
            .padding([5, 13])
            .on_press(msg)
            .style(move |t, s| style::mini_toggle(on, t, s))
    ]
    .spacing(12)
    .align_y(Center)
    .into()
}

fn guide_kv<'a>(label: &'static str, body: &'a str) -> Element<'a, Message> {
    row![
        text(label)
            .size(11)
            .font(style::LABEL)
            .color(style::DIM)
            .width(155),
        text(body).size(12).color(style::TEXT_2).width(Fill)
    ]
    .spacing(10)
    .into()
}

// ============================================================================
// STAGE 02: DEEP TOKENIZER STUDIO, DIFFERENCES GUIDE & 4-WAY COMPARISON ARENA
// ============================================================================

pub fn stage_tokenizer_deep_view(app: &App) -> Element<'_, Message> {
    let tk_cfg = &app.cfg.tokenizer;
    let guide = tokenizer_guide(tk_cfg.kind);

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

    let vocab_or_file: Element<'_, Message> = if tk_cfg.kind == TokenizerKind::PretrainedFile {
        column![
            text("PRETRAINED HUGGING FACE TOKENIZER.JSON PATH")
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
            mini_stepper(
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
            .style(style::card),
            mini_stepper(
                "MIN MERGE FREQ",
                tk_cfg.min_frequency.to_string(),
                Message::AdjustMinFreq(-1),
                Message::AdjustMinFreq(1)
            ),
        ]
        .spacing(10)
        .into()
    };

    // Pre-tokenization & digit splitting pills
    let mut pre_pills = row![].spacing(6);
    for mode in PreTokenizeMode::ALL {
        let active = tk_cfg.pre_tokenize == mode;
        pre_pills = pre_pills.push(
            button(text(mode.label()).size(11))
                .padding([5, 10])
                .on_press(Message::SelectPreTokenize(mode))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut digit_pills = row![].spacing(6);
    for dp in DigitPolicy::ALL {
        let active = tk_cfg.digit_policy == dp;
        digit_pills = digit_pills.push(
            button(text(dp.label()).size(11))
                .padding([5, 10])
                .on_press(Message::SelectDigitPolicy(dp))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut norm_pills = row![].spacing(6);
    for un in UnicodeNorm::ALL {
        let active = tk_cfg.normalization == un;
        norm_pills = norm_pills.push(
            button(text(un.label()).size(11))
                .padding([5, 10])
                .on_press(Message::SelectUnicodeNorm(un))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut pad_pills = row![].spacing(6);
    for (mult, lbl) in [
        (0usize, "Unpadded"),
        (64usize, "Pad to 64× (CPU SIMD)"),
        (128usize, "Pad to 128× (GPU Tiles)"),
    ] {
        let active = tk_cfg.pad_to_multiple == mult;
        pad_pills = pad_pills.push(
            button(text(lbl).size(11))
                .padding([5, 10])
                .on_press(Message::SelectVocabPadMultiple(mult))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    // Active tokenizer token chips
    let mut token_badges = column![].spacing(6);
    let mut current_line = row![].spacing(6);
    let mut line_chars = 0usize;
    for (id, disp) in app.tokenizer_preview.tokens.iter().take(48) {
        let label = format!("{disp} #{id}");
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

    // 4-way Arena comparison table
    let mut arena_rows = column![].spacing(8);
    for row_data in &app.tokenizer_arena {
        let is_selected = row_data.kind == tk_cfg.kind;
        let sample_snip: String = row_data
            .preview_tokens
            .iter()
            .take(9)
            .map(|(_, s)| format!("[{s}]"))
            .collect::<Vec<_>>()
            .join(" ");

        arena_rows = arena_rows.push(
            container(
                column![
                    row![
                        text(format!(
                            "{}{}",
                            row_data.kind.label(),
                            if is_selected { "  · ACTIVE" } else { "" }
                        ))
                        .size(12.5)
                        .font(style::STRONG)
                        .color(if is_selected { style::OK } else { style::WHITE })
                        .width(FillPortion(2)),
                        text(format!("vocab {}", row_data.actual_vocab_size))
                            .size(11.5)
                            .color(style::GREY)
                            .width(FillPortion(1)),
                        text(format!("{} tok", row_data.token_count))
                            .size(11.5)
                            .font(style::LABEL)
                            .color(style::WHITE)
                            .width(FillPortion(1)),
                        text(format!("{:.2} ch/tok", row_data.chars_per_token))
                            .size(11.5)
                            .color(style::TEXT_2)
                            .width(FillPortion(1)),
                        text(format!("{:.2} tok/word", row_data.fertility_tok_per_word))
                            .size(11.5)
                            .color(style::TEXT_2)
                            .width(FillPortion(1)),
                        text(format!("~{} words/ctx", row_data.est_words_per_ctx))
                            .size(11.5)
                            .color(style::OK)
                            .width(FillPortion(1)),
                        button(text("Use").size(10.5).font(style::LABEL))
                            .padding([3, 9])
                            .on_press(Message::SelectTokenizerKind(row_data.kind))
                            .style(move |t, s| style::mini_toggle(is_selected, t, s)),
                    ]
                    .spacing(8)
                    .align_y(Center),
                    text(format!("Splits: {sample_snip}"))
                        .size(11)
                        .color(style::DIM)
                ]
                .spacing(4),
            )
            .width(Fill)
            .padding(11)
            .style(style::surface),
        );
    }

    let tk_summary = app
        .tokenizer
        .as_ref()
        .map(|tk| tk.summary().to_owned())
        .unwrap_or_else(|| "Not built yet".to_owned());

    column![
        eyebrow_header(
            "STAGE 02 / NATIVE RUST TOKENIZER STUDIO",
            "Choose, Customize & Compare Tokenizers",
            "Understand how each subword algorithm splits text, configure pre-tokenization & math digit rules, and compare all 4 scratch tokenizers live."
        ),
        // Card 1: Algorithm picker + Deep Differences Guide
        container(
            column![
                row![
                    text("SELECT TOKENIZER FAMILY")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(tk_cfg.kind.family_badge())
                        .size(11)
                        .font(style::LABEL)
                        .color(style::OK)
                ]
                .align_y(Center),
                kind_pills,
                container(
                    column![
                        text(guide.subtitle)
                            .size(12.5)
                            .font(style::STRONG)
                            .color(style::WHITE),
                        guide_kv("HOW IT WORKS", guide.mechanism),
                        guide_kv("OOV / <UNK> POLICY", guide.oov_behavior),
                        guide_kv("COMPRESSION", guide.compression_profile),
                        guide_kv("TRANSFORMER IMPACT", guide.transformer_impact),
                        guide_kv("STRENGTHS", guide.strengths),
                        guide_kv("TRADE-OFFS", guide.tradeoffs),
                    ]
                    .spacing(6)
                )
                .width(Fill)
                .padding(13)
                .style(style::surface),
                vocab_or_file,
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Card 2: Deep Pre-tokenization, Digits, Hardware Alignment & Special Tokens
        container(
            column![
                text("PRE-TOKENIZATION, MATH DIGIT SPLITTING & HARDWARE ALIGNMENT")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                column![
                    text("Boundary splitting rule").size(11.5).color(style::GREY),
                    pre_pills
                ]
                .spacing(5),
                column![
                    text("Number & arithmetic policy (crucial for Transformer math generalization)")
                        .size(11.5)
                        .color(style::GREY),
                    digit_pills
                ]
                .spacing(5),
                column![
                    text("Unicode normalization").size(11.5).color(style::GREY),
                    norm_pills
                ]
                .spacing(5),
                column![
                    text("Hardware tensor-tile vocabulary alignment").size(11.5).color(style::GREY),
                    pad_pills
                ]
                .spacing(5),
                row![
                    mini_stepper(
                        "SUBWORD DROPOUT (TRAIN REG.)",
                        format!("{:.2}", tk_cfg.subword_dropout),
                        Message::AdjustSubwordDropout(-0.02),
                        Message::AdjustSubwordDropout(0.02)
                    ),
                    container(
                        column![
                            text("CUSTOM SPECIAL TOKENS (COMMA-SEPARATED)")
                                .size(10.5)
                                .font(style::LABEL)
                                .color(style::DIM),
                            text_input("<think>,</think>,<tool>", &tk_cfg.custom_special_tokens)
                                .on_input(Message::EditCustomSpecials)
                                .padding([7, 10])
                                .size(12.5)
                                .style(style::composer_input)
                        ]
                        .spacing(6)
                    )
                    .width(FillPortion(2))
                    .padding(12)
                    .style(style::card)
                ]
                .spacing(10),
                switch_row(
                    "UTF-8 Byte Fallback (<0xXX>)",
                    "Decomposes unseen Unicode characters into hex byte tokens in WordPiece/Unigram so <unk> rate stays 0%.",
                    tk_cfg.byte_fallback,
                    Message::ToggleByteFallback
                ),
                switch_row(
                    "Sequence packing",
                    "Concatenates documents end-to-end with <bos>/<eos> separators so zero FLOPs are wasted on padding.",
                    tk_cfg.sequence_packing,
                    Message::ToggleSequencePacking
                ),
                switch_row(
                    "Insert <bos> and <eos> boundary tokens",
                    "Marks exact document boundaries for clean autoregressive stopping.",
                    tk_cfg.add_bos_eos,
                    Message::ToggleBosEos
                ),
                row![
                    button(
                        text("Train / Rebuild Active Tokenizer")
                            .size(12.5)
                            .font(style::STRONG)
                            .color(style::BLACK)
                    )
                    .padding([9, 16])
                    .on_press(Message::BuildTokenizer)
                    .style(style::primary_button),
                    text(tk_summary).size(12).color(style::OK).width(Fill),
                    button(text("Next: 03 Architecture  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Architecture))
                        .style(style::control_button)
                ]
                .spacing(12)
                .align_y(Center)
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Card 3: Live Probe & 4-Way Comparison Arena
        container(
            column![
                row![
                    text("SIDE-BY-SIDE 4-TOKENIZER ARENA & LIVE PROBE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(
                        text("Compare All 4 Scratch Tokenizers")
                            .size(11.5)
                            .font(style::STRONG)
                    )
                    .padding([6, 13])
                    .on_press(Message::RunTokenizerArena)
                    .style(style::control_button)
                ]
                .align_y(Center),
                text_input("Type code, math, or prose to inspect splits…", &app.tokenizer_sample)
                    .on_input(Message::EditTokenizerSample)
                    .padding([9, 12])
                    .size(13)
                    .style(style::composer_input),
                text(format!(
                    "Active {} split ({} tokens · {:.2} chars/token):",
                    tk_cfg.kind.label(),
                    app.tokenizer_preview.tokens.len(),
                    app.tokenizer_preview.chars_per_token
                ))
                .size(11.5)
                .color(style::GREY),
                token_badges,
                space().height(4),
                text(format!(
                    "4-Algorithm Comparison on Active Corpus (context window = {} tokens):",
                    app.cfg.model.seq_len
                ))
                .size(11.5)
                .font(style::LABEL)
                .color(style::DIM),
                arena_rows,
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

// ============================================================================
// EXTRA TRANSFORMER ENGINE #1 CONTROLS (PLUGGED INTO STAGE 03)
// ============================================================================

pub fn transformer_advanced_card(app: &App) -> Element<'_, Message> {
    let m = &app.cfg.model;

    let mut place_pills = row![].spacing(6);
    for np in NormPlacement::ALL {
        let active = m.norm_placement == np;
        place_pills = place_pills.push(
            button(text(np.label()).size(11))
                .padding([5, 11])
                .on_press(Message::SelectNormPlacement(np))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut rope_scale_pills = row![].spacing(6);
    for rs in RopeScalingMode::ALL {
        let active = m.rope_scaling == rs;
        rope_scale_pills = rope_scale_pills.push(
            button(text(rs.label()).size(11))
                .padding([5, 11])
                .on_press(Message::SelectRopeScaling(rs))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut embed_pills = row![].spacing(6);
    for es in EmbedScaleMode::ALL {
        let active = m.embed_scale == es;
        embed_pills = embed_pills.push(
            button(text(es.label()).size(11))
                .padding([5, 11])
                .on_press(Message::SelectEmbedScale(es))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut resid_pills = row![].spacing(6);
    for rsm in ResidualScaleMode::ALL {
        let active = m.residual_scale_mode == rsm;
        resid_pills = resid_pills.push(
            button(text(rsm.label()).size(11))
                .padding([5, 11])
                .on_press(Message::SelectResidualScaleMode(rsm))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    container(
        column![
            text("ENGINE #1 DEEP TRANSFORMER TOPOLOGY & LOGIT SOFT-CAPPING")
                .size(10.5)
                .font(style::LABEL)
                .color(style::DIM),
            row![
                text("Norm placement:").size(12).color(style::GREY).width(135),
                place_pills
            ]
            .align_y(Center),
            row![
                text("RoPE scaling:").size(12).color(style::GREY).width(135),
                rope_scale_pills
            ]
            .align_y(Center),
            row![
                text("Embedding scale:").size(12).color(style::GREY).width(135),
                embed_pills
            ]
            .align_y(Center),
            row![
                text("Residual scaling:").size(12).color(style::GREY).width(135),
                resid_pills
            ]
            .align_y(Center),
            row![
                mini_stepper(
                    "ATTN LOGIT SOFTCAP (GEMMA-2)",
                    if m.attn_logit_softcap <= 0.5 {
                        "Off".into()
                    } else {
                        format!("{:.0}", m.attn_logit_softcap)
                    },
                    Message::AdjustAttnSoftcap(-10.0),
                    Message::AdjustAttnSoftcap(10.0)
                ),
                mini_stepper(
                    "FINAL LOGIT SOFTCAP",
                    if m.final_logit_softcap <= 0.5 {
                        "Off".into()
                    } else {
                        format!("{:.0}", m.final_logit_softcap)
                    },
                    Message::AdjustFinalSoftcap(-10.0),
                    Message::AdjustFinalSoftcap(10.0)
                ),
                mini_stepper(
                    "TRUNCATED INIT CLIP (±σ)",
                    format!("±{:.1}σ", m.truncated_sigma),
                    Message::AdjustTruncSigma(-0.5),
                    Message::AdjustTruncSigma(0.5)
                ),
            ]
            .spacing(10),
        ]
        .spacing(10),
    )
    .width(Fill)
    .padding(16)
    .style(style::card)
    .into()
}

// ============================================================================
// STAGE 04: SYSTEM HARDWARE PROBE, CPU vs GPU SELECTOR & CUSTOM OPTIMIZATION PLAN
// ============================================================================

pub fn stage_hardware_view(app: &App) -> Element<'_, Message> {
    let hw = &app.hardware;
    let exec = &app.cfg.hardware_exec;
    let plan = &app.optimization_plan;
    let ps = &plan.summary;

    let simd_line = if hw.cpu.simd_features.is_empty() {
        "Portable auto-vectorized ISA".to_owned()
    } else {
        hw.cpu.simd_features.join(" · ")
    };

    let mut gpu_cards = column![].spacing(8);
    if hw.gpus.is_empty() {
        gpu_cards = gpu_cards.push(
            container(
                text("No Vulkan / DirectX 12 / Metal GPU adapter reported on this host — Multi-Threaded SIMD CPU backend active.")
                    .size(12)
                    .color(style::GREY),
            )
            .width(Fill)
            .padding(12)
            .style(style::surface),
        );
    } else {
        for gpu in &hw.gpus {
            let selected = exec.target == ComputeTarget::Gpu && exec.preferred_gpu_index == gpu.index;
            gpu_cards = gpu_cards.push(
                container(
                    row![
                        column![
                            row![
                                text(format!("GPU #{} · {}", gpu.index, gpu.name))
                                    .size(13)
                                    .font(style::STRONG)
                                    .color(style::WHITE),
                                container(
                                    text(format!("{} · {}", gpu.backend, gpu.device_type))
                                        .size(10.5)
                                        .font(style::LABEL)
                                        .color(if gpu.is_hardware_gpu { style::OK } else { style::GREY })
                                )
                                .padding([2, 8])
                                .style(style::badge),
                            ]
                            .spacing(8)
                            .align_y(Center),
                            text(format!(
                                "Max Buffer: {} MB · Storage Binding: {} MB · Max Workgroup: {} · Compute: {} · Shader FP16: {}",
                                gpu.max_buffer_mb,
                                gpu.max_storage_binding_mb,
                                gpu.max_workgroup_size_x,
                                if gpu.supports_compute { "Yes" } else { "No" },
                                if gpu.supports_f16 { "Yes" } else { "No" },
                            ))
                            .size(11.5)
                            .color(style::GREY),
                        ]
                        .spacing(4)
                        .width(Fill),
                        button(
                            text(if selected { "Selected GPU" } else { "Use this GPU" })
                                .size(11)
                                .font(style::LABEL)
                        )
                        .padding([6, 12])
                        .on_press(Message::SelectPreferredGpu(gpu.index))
                        .style(move |t, s| style::mini_toggle(selected, t, s))
                    ]
                    .spacing(12)
                    .align_y(Center),
                )
                .width(Fill)
                .padding(12)
                .style(style::surface),
            );
        }
    }

    // Compute target selector
    let mut target_pills = row![].spacing(8);
    for t_opt in ComputeTarget::ALL {
        let active = exec.target == t_opt;
        target_pills = target_pills.push(
            button(text(t_opt.label()).size(11.5).font(style::LABEL))
                .padding([7, 13])
                .on_press(Message::SelectComputeTarget(t_opt))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let mut prec_pills = row![].spacing(8);
    for pm in PrecisionMode::ALL {
        let active = exec.precision == pm;
        prec_pills = prec_pills.push(
            button(text(pm.label()).size(11.5).font(style::LABEL))
                .padding([6, 12])
                .on_press(Message::SelectPrecisionMode(pm))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let bench_block: Element<'_, Message> = if let Some(b) = &app.compute_benchmark {
        let gpu_line = match (&b.gpu_adapter_name, b.gpu_ms, b.gpu_gflops) {
            (Some(name), Some(ms), Some(gf)) => format!(
                "{name} ({}) -> {ms:.2} ms · {gf:.1} GFLOP/s (max |Δ| = {:.2e})",
                b.gpu_backend.as_deref().unwrap_or("WGPU"),
                b.max_abs_diff.unwrap_or(0.0)
            ),
            _ => "No compute GPU benchmarked on this host".to_owned(),
        };
        container(
            column![
                row![
                    text(format!("LIVE {}×{} SGEMM BENCHMARK", b.matrix_dim, b.matrix_dim))
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!("Fastest: {}", b.recommended_winner))
                        .size(11.5)
                        .font(style::STRONG)
                        .color(style::OK)
                ]
                .align_y(Center),
                text(format!(
                    "CPU ({} Rayon threads) -> {:.2} ms · {:.1} GFLOP/s",
                    b.cpu_threads, b.cpu_ms, b.cpu_gflops
                ))
                .size(12)
                .color(style::TEXT_2),
                text(format!("GPU (WGSL 16×16 Tiled fma) -> {gpu_line}"))
                    .size(12)
                    .color(style::TEXT_2),
                text(b.note.clone()).size(11.5).color(style::GREY),
            ]
            .spacing(4),
        )
        .width(Fill)
        .padding(13)
        .style(style::surface)
        .into()
    } else {
        space().height(0).into()
    };

    let mut rationale_col = column![].spacing(5);
    for (idx, item) in plan.rationale.iter().enumerate() {
        rationale_col = rationale_col.push(
            text(format!("{}. {item}", idx + 1))
                .size(12)
                .color(style::TEXT_2),
        );
    }

    column![
        eyebrow_header(
            "STAGE 04 / HARDWARE PROBE & CUSTOM OPTIMIZATION COMPILER",
            "System Hardware, CPU vs GPU & Custom Execution Plan",
            "Inspects your CPU vector ISA, RAM, and Vulkan/DX12/Metal GPUs, lets you select CPU or GPU, and synthesizes a custom optimization plan for your model."
        ),
        // Card 1: Detected Hardware
        container(
            column![
                row![
                    text("DETECTED SYSTEM HARDWARE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(text("Rescan Hardware").size(11.5).font(style::LABEL))
                        .padding([6, 12])
                        .on_press(Message::RescanHardware)
                        .style(style::control_button),
                    button(
                        text("Benchmark CPU vs WGSL GPU")
                            .size(11.5)
                            .font(style::STRONG)
                    )
                    .padding([6, 12])
                    .on_press(Message::RunComputeBenchmark)
                    .style(style::control_button),
                ]
                .spacing(8)
                .align_y(Center),
                row![
                    container(
                        column![
                            text("HOST CPU & VECTOR ISA")
                                .size(10.5)
                                .font(style::LABEL)
                                .color(style::DIM),
                            text(hw.cpu.brand.clone())
                                .size(13.5)
                                .font(style::STRONG)
                                .color(style::WHITE),
                            text(format!(
                                "{} · {} logical cores · {}",
                                hw.cpu.arch,
                                hw.cpu.logical_cores,
                                hw.cpu.simd_tier()
                            ))
                            .size(12)
                            .color(style::OK),
                            text(format!("Detected SIMD flags: {simd_line}"))
                                .size(11.5)
                                .color(style::GREY),
                        ]
                        .spacing(4)
                    )
                    .width(FillPortion(2))
                    .padding(13)
                    .style(style::surface),
                    container(
                        column![
                            text("SYSTEM MEMORY (RAM)")
                                .size(10.5)
                                .font(style::LABEL)
                                .color(style::DIM),
                            text(format!("{:.1} GB Total", hw.memory.total_ram_mb as f64 / 1024.0))
                                .size(15)
                                .font(style::STRONG)
                                .color(style::WHITE),
                            text(format!(
                                "{:.1} GB Available ({} MB)",
                                hw.memory.available_ram_mb as f64 / 1024.0,
                                hw.memory.available_ram_mb
                            ))
                            .size(12)
                            .color(style::OK),
                            text("Zero external CUDA/Python install required")
                                .size(11)
                                .color(style::DIM),
                        ]
                        .spacing(4)
                    )
                    .width(FillPortion(1))
                    .padding(13)
                    .style(style::surface),
                ]
                .spacing(10),
                text("ENUMERATED WGPU GRAPHICS / COMPUTE ADAPTERS (VULKAN · DIRECTX 12 · METAL)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                gpu_cards,
                bench_block,
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Card 2: CPU vs GPU Selection & Execution Knobs
        container(
            column![
                text("CHOOSE EXECUTION DEVICE (CPU VS GPU) & MEMORY CONTROLS")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                target_pills,
                text("PRECISION & ACCUMULATOR STRATEGY")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                prec_pills,
                row![
                    mini_stepper(
                        "CPU RAYON THREADS",
                        app.cfg.hyper.compute_threads.to_string(),
                        Message::AdjustComputeThreads(-1),
                        Message::AdjustComputeThreads(1)
                    ),
                    mini_stepper(
                        "MICRO-BATCH SIZE",
                        app.cfg.hyper.batch_size.to_string(),
                        Message::AdjustBatchSize(-1),
                        Message::AdjustBatchSize(1)
                    ),
                    mini_stepper(
                        "GRAD ACCUM STEPS",
                        app.cfg.hyper.grad_accum_steps.to_string(),
                        Message::AdjustGradAccum(-1),
                        Message::AdjustGradAccum(1)
                    ),
                ]
                .spacing(10),
                switch_row(
                    "Activation checkpointing (√L memory schedule)",
                    "Recomputes intermediate layer activations on backward pass to slash activation RAM on long contexts.",
                    exec.activation_checkpointing,
                    Message::ToggleActivationCheckpointing
                ),
                switch_row(
                    "Pad tokenizer vocabulary to hardware tile multiple (64× CPU / 128× GPU)",
                    "Eliminates unaligned tail workgroups in token embedding and LM-head matrix multiplications.",
                    exec.pad_vocab_for_hardware,
                    Message::ToggleHardwareVocabPad
                ),
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Card 3: Synthesized Custom Optimization Plan + Exportable TOML Script
        container(
            column![
                row![
                    column![
                        text("SYNTHESIZED CUSTOM OPTIMIZATION PLAN")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM),
                        text(format!("{} · {}", ps.resolved_device_label, ps.backend_api))
                            .size(14)
                            .font(style::STRONG)
                            .color(if ps.fits_in_budget { style::OK } else { style::DANGER }),
                    ]
                    .spacing(3)
                    .width(Fill),
                    button(
                        text("Apply Recommended Plan")
                            .size(12)
                            .font(style::STRONG)
                            .color(style::BLACK)
                    )
                    .padding([8, 15])
                    .on_press(Message::ApplyHardwareOptimizationPlan)
                    .style(style::primary_button),
                    button(text("Export Plan (.toml)").size(11.5).font(style::LABEL))
                        .padding([8, 13])
                        .on_press(Message::ExportOptimizationScript)
                        .style(style::control_button),
                ]
                .spacing(8)
                .align_y(Center),
                row![
                    container(
                        column![
                            text("RECOMMENDED BATCH").size(10).font(style::LABEL).color(style::DIM),
                            text(format!(
                                "{} × {} accum ({} tok/step)",
                                ps.recommended_batch_size,
                                ps.recommended_grad_accum,
                                ps.effective_tokens_per_step
                            ))
                            .size(12.5)
                            .font(style::LABEL)
                            .color(style::WHITE),
                        ]
                        .spacing(3)
                    )
                    .width(FillPortion(1))
                    .padding(11)
                    .style(style::surface),
                    container(
                        column![
                            text("TILE & WORKGROUP").size(10).font(style::LABEL).color(style::DIM),
                            text(format!(
                                "Tile {:?} · WG {:?}",
                                ps.tile_m_n_k, ps.workgroup_dims
                            ))
                            .size(12.5)
                            .font(style::LABEL)
                            .color(style::WHITE),
                        ]
                        .spacing(3)
                    )
                    .width(FillPortion(1))
                    .padding(11)
                    .style(style::surface),
                    container(
                        column![
                            text("PEAK VS SAFE BUDGET").size(10).font(style::LABEL).color(style::DIM),
                            text(format!(
                                "{:.1} MB / {:.0} MB ({:.0}% free)",
                                ps.estimated_peak_mb, ps.device_budget_mb, ps.headroom_pct
                            ))
                            .size(12.5)
                            .font(style::LABEL)
                            .color(if ps.fits_in_budget { style::OK } else { style::DANGER }),
                        ]
                        .spacing(3)
                    )
                    .width(FillPortion(1))
                    .padding(11)
                    .style(style::surface),
                ]
                .spacing(10),
                container(rationale_col)
                    .width(Fill)
                    .padding(13)
                    .style(style::surface),
                text("GENERATED CUSTOM EXECUTION SCRIPT (optimization_plan.toml)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                container(
                    scrollable(
                        text(plan.custom_script_toml.clone())
                            .size(11.5)
                            .color(style::TEXT_2)
                    )
                    .height(175)
                    .style(style::quiet_scroll)
                )
                .width(Fill)
                .padding(12)
                .style(style::surface),
                row![
                    space().width(Fill),
                    button(text("Next: 05 Seed & Genesis  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Repro))
                        .style(style::control_button)
                ]
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
    ]
    .spacing(16)
    .into()
}

// ============================================================================
// STAGE 05: SEED CONTROL, PROVENANCE EXPORT & GENESIS RANDOM STATE (STEP = 0)
// ============================================================================

pub fn stage_repro_view(app: &App) -> Element<'_, Message> {
    let seeds = &app.cfg.seeds;

    let mut algo_pills = row![].spacing(7);
    for algo in PrngAlgorithm::ALL {
        let active = seeds.algorithm == algo;
        algo_pills = algo_pills.push(
            button(text(algo.label()).size(11).font(style::LABEL))
                .padding([6, 11])
                .on_press(Message::SelectPrngAlgorithm(algo))
                .style(move |t, s| style::mini_toggle(active, t, s)),
        );
    }

    let genesis_card: Element<'_, Message> = if let Some(rep) = &app.genesis_report {
        let floats_preview = rep
            .first_16_embedding_floats
            .iter()
            .take(12)
            .map(|v| format!("{v:+.5}"))
            .collect::<Vec<_>>()
            .join(", ");

        let mut tensor_rows = column![].spacing(4);
        for st in rep.tensor_stats.iter().take(8) {
            tensor_rows = tensor_rows.push(
                row![
                    text(st.name.clone())
                        .size(11)
                        .font(style::LABEL)
                        .color(style::WHITE)
                        .width(FillPortion(3)),
                    text(format!("{:?} ({})", st.shape, format_count(st.params)))
                        .size(11)
                        .color(style::GREY)
                        .width(FillPortion(2)),
                    text(format!("μ={:+.4}  σ={:.4}", st.mean, st.std))
                        .size(11)
                        .color(style::TEXT_2)
                        .width(FillPortion(2)),
                    text(format!("[{:+.3}, {:+.3}]", st.min, st.max))
                        .size(11)
                        .color(style::DIM)
                        .width(FillPortion(2)),
                ]
                .spacing(8)
                .align_y(Center),
            );
        }

        let export_paths_note = match (
            &rep.exported_provenance_path,
            &rep.exported_genesis_safetensors_path,
        ) {
            (Some(prov), Some(gen_st)) => format!(
                "Saved: {}  +  {}",
                prov.display(),
                gen_st.display()
            ),
            (Some(prov), None) => format!("Saved provenance bundle: {}", prov.display()),
            _ => format!(
                "Default run export folder: {}",
                app.active_run_dir().display()
            ),
        };

        container(
            column![
                row![
                    text("STEP-0 INITIAL RANDOM-FILLED STATE INSPECTOR")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(text("Re-inspect Step-0 State").size(11).font(style::LABEL))
                        .padding([5, 11])
                        .on_press(Message::InspectGenesisNow)
                        .style(style::control_button),
                ]
                .align_y(Center),
                container(
                    column![
                        text(format!("Canonical Weights SHA-256: {}", rep.sha256_hex))
                            .size(11.5)
                            .font(style::STRONG)
                            .color(style::OK),
                        text(format!(
                            "Source: {} · {} tensors ({} params) · global mean {:+.5} · std {:.5} · range [{:+.4}, {:+.4}]",
                            rep.source_label,
                            rep.total_tensors,
                            format_count(rep.total_params),
                            rep.global_mean,
                            rep.global_std,
                            rep.global_min,
                            rep.global_max
                        ))
                        .size(11.5)
                        .color(style::TEXT_2),
                        text(format!(
                            "tok_embeddings.weight[0..12] = [{floats_preview}, …]"
                        ))
                        .size(11)
                        .color(style::GREY),
                    ]
                    .spacing(4)
                )
                .width(Fill)
                .padding(12)
                .style(style::surface),
                text("SAMPLE STEP-0 TENSORS BEFORE ANY GRADIENT STEP")
                    .size(10)
                    .font(style::LABEL)
                    .color(style::DIM),
                container(tensor_rows)
                    .width(Fill)
                    .padding(11)
                    .style(style::surface),
                text(export_paths_note).size(11).color(style::GREY),
            ]
            .spacing(9),
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
        .into()
    } else {
        container(
            button(text("Inspect Step-0 Random Fill").size(12))
                .padding([8, 14])
                .on_press(Message::InspectGenesisNow)
                .style(style::control_button),
        )
        .width(Fill)
        .padding(16)
        .style(style::card)
        .into()
    };

    column![
        eyebrow_header(
            "STAGE 05 / DETERMINISTIC SEEDS, HARDWARE PROVENANCE & GENESIS STATE",
            "Seeds, Hardware Provenance & Initial Random State Export",
            "Control every PRNG stream, export full model settings + host hardware provenance, and optionally save or reload the exact step-0 random-filled weights."
        ),
        // Card 1: PRNG & Seed Hierarchy
        container(
            column![
                text("CROSS-HARDWARE PORTABLE PRNG ENGINE")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                algo_pills,
                text(seeds.algorithm.description())
                    .size(12)
                    .color(style::GREY),
                row![
                    column![
                        text("MASTER SEED (64-BIT)")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM),
                        row![
                            text_input("42", &app.seed_input)
                                .on_input(Message::EditMasterSeed)
                                .padding([8, 11])
                                .size(13)
                                .width(Fill)
                                .style(style::composer_input),
                            button(text("Roll Entropy Seed").size(11.5).font(style::LABEL))
                                .padding([8, 13])
                                .on_press(Message::RandomizeSeed)
                                .style(style::control_button),
                        ]
                        .spacing(8)
                        .align_y(Center)
                    ]
                    .spacing(5)
                    .width(Fill),
                ],
                switch_row(
                    "Lock subsystem seeds to Master Seed (domain-separated derivation)",
                    "Derives independent collision-free streams for Weight Init, Data Shuffle, Dropout/MoE Jitter, and Sampling from Master Seed. Turn OFF to set each manually.",
                    seeds.lock_subsystems_to_master,
                    Message::ToggleLockSubsystemsToMaster
                ),
                row![
                    column![
                        text("Weight Init Seed").size(11).color(style::GREY),
                        text_input("weight seed", &app.weight_seed_input)
                            .on_input(Message::EditWeightSeed)
                            .padding([7, 10])
                            .size(12.5)
                            .style(style::composer_input)
                    ]
                    .spacing(4)
                    .width(FillPortion(1)),
                    column![
                        text("Data Order Seed").size(11).color(style::GREY),
                        text_input("data seed", &app.data_seed_input)
                            .on_input(Message::EditDataSeed)
                            .padding([7, 10])
                            .size(12.5)
                            .style(style::composer_input)
                    ]
                    .spacing(4)
                    .width(FillPortion(1)),
                    column![
                        text("Dropout / MoE Seed").size(11).color(style::GREY),
                        text_input("stochastic seed", &app.stochastic_seed_input)
                            .on_input(Message::EditStochasticSeed)
                            .padding([7, 10])
                            .size(12.5)
                            .style(style::composer_input)
                    ]
                    .spacing(4)
                    .width(FillPortion(1)),
                    column![
                        text("Playground Seed").size(11).color(style::GREY),
                        text_input("42", &app.sample_seed_input)
                            .on_input(Message::EditSampleSeed)
                            .padding([7, 10])
                            .size(12.5)
                            .style(style::composer_input)
                    ]
                    .spacing(4)
                    .width(FillPortion(1)),
                ]
                .spacing(10),
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        // Card 2: Export Settings + Hardware + Initial Random State
        container(
            column![
                text("PROVENANCE & INITIAL RANDOM-FILLED STATE (GENESIS SAFETENSORS)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                switch_row(
                    "Archive initial random-filled state (genesis_step0.safetensors) when training starts",
                    "Writes the exact pre-training random weight tensors + SHA-256 manifest to disk before gradient step 1 modifies any parameter.",
                    seeds.auto_export_genesis_init,
                    Message::ToggleAutoExportGenesis
                ),
                column![
                    text("OPTIONAL: RELOAD INITIAL RANDOM STATE FROM SAVED SAFETENSORS")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    text_input(
                        "Leave empty to sample from PRNG, or enter /path/to/genesis_step0.safetensors…",
                        &seeds.genesis_reload_path
                    )
                    .on_input(Message::EditGenesisReloadPath)
                    .padding([8, 12])
                    .size(12.5)
                    .style(style::composer_input),
                ]
                .spacing(5),
                row![
                    button(
                        text("Export Settings + Hardware Provenance")
                            .size(12)
                            .font(style::LABEL)
                    )
                    .padding([9, 14])
                    .on_press(Message::ExportProvenanceBundle {
                        include_genesis_weights: false
                    })
                    .style(style::control_button),
                    button(
                        text("Export Settings + Hardware + Genesis Random Weights")
                            .size(12)
                            .font(style::STRONG)
                            .color(style::BLACK)
                    )
                    .padding([9, 15])
                    .on_press(Message::ExportProvenanceBundle {
                        include_genesis_weights: true
                    })
                    .style(style::primary_button),
                    space().width(Fill),
                    button(text("Next: 06 Train  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Train))
                        .style(style::control_button),
                ]
                .spacing(10)
                .align_y(Center),
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        genesis_card,
    ]
    .spacing(16)
    .into()
}
