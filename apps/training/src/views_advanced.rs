//! Purpose: Renders progressive (`Simple` / `Normal` / `Advanced`) views for Model Size Prediction, Parameter-to-Token Ratio Adjustment, Tokenizer Studio, Hardware & Popular GPU/CPU Simulator (`04`), and Seed/Genesis Provenance (`05`).

use iced::widget::{button, column, container, row, scrollable, space, text, text_input};
use iced::{Center, Element, Fill, FillPortion};

use archx_shared::style;

use crate::app::{App, Message, PipelineStage};
use crate::config::{
    ComputeTarget, DigitPolicy, EmbedScaleMode, NormPlacement, PreTokenizeMode, PrecisionMode,
    ResidualScaleMode, RopeScalingMode, TokenizerKind, UiComplexity, UnicodeNorm, format_count,
    format_size_mb,
};
use crate::hardware::ReferenceHardwarePreset;
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
        text(subtitle).size(13).color(style::GREY)
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

fn mode_upsell_footer<'a>(current: UiComplexity) -> Element<'a, Message> {
    match current {
        UiComplexity::Simple => row![
            text("Showing clean Simple essentials.")
                .size(11.5)
                .color(style::DIM)
                .width(Fill),
            button(text("Show Normal Controls").size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectUiComplexity(UiComplexity::Standard))
                .style(style::tiny_button),
            button(text("Show All Research Settings").size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectUiComplexity(UiComplexity::Expert))
                .style(style::tiny_button),
        ]
        .spacing(8)
        .align_y(Center)
        .into(),
        UiComplexity::Standard => row![
            text("Showing Normal builder controls.")
                .size(11.5)
                .color(style::DIM)
                .width(Fill),
            button(text("Switch to Simple").size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectUiComplexity(UiComplexity::Simple))
                .style(style::tiny_button),
            button(text("Unlock Advanced Research Controls").size(11).font(style::LABEL))
                .padding([5, 11])
                .on_press(Message::SelectUiComplexity(UiComplexity::Expert))
                .style(style::tiny_button),
        ]
        .spacing(8)
        .align_y(Center)
        .into(),
        UiComplexity::Expert => space().height(0).into(),
    }
}

fn size_tile<'a>(
    eyebrow: &'static str,
    big_val: String,
    sub: String,
    accent: bool,
) -> Element<'a, Message> {
    container(
        column![
            text(eyebrow).size(10).font(style::LABEL).color(style::DIM),
            text(big_val)
                .size(16.5)
                .font(style::DISPLAY)
                .color(if accent { style::OK } else { style::WHITE }),
            text(sub).size(11).color(style::GREY),
        ]
        .spacing(3),
    )
    .width(FillPortion(1))
    .padding(12)
    .style(style::surface)
    .into()
}

// ============================================================================
// MODEL FILE SIZE PREDICTOR & PARAMETER-TO-TOKEN RATIO ADJUSTER (STAGE 03)
// ============================================================================

pub fn size_and_ratio_cards(app: &App) -> Element<'_, Message> {
    let sz = app.cfg.predict_sizes();
    let ratio = app.cfg.token_param_ratio(app.estimated_corpus_tokens());
    let simple = app.ui_complexity == UiComplexity::Simple;

    // 1. Model Disk & RAM Size Predictor Card
    let size_card: Element<'_, Message> = if simple {
        container(
            column![
                row![
                    text("PREDICTED AI FILE SIZE & MEMORY")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!("{} parameters", format_count(sz.total_params)))
                        .size(11.5)
                        .font(style::LABEL)
                        .color(style::OK),
                ]
                .align_y(Center),
                row![
                    size_tile(
                        "SAVED MODEL FILE",
                        format_size_mb(sz.fp32_safetensors_mb),
                        "Exact .safetensors file".to_owned(),
                        true,
                    ),
                    size_tile(
                        "COMPACT / 4-BIT EST.",
                        format!(
                            "{} / {}",
                            format_size_mb(sz.fp16_bf16_mb),
                            format_size_mb(sz.int4_quant_mb)
                        ),
                        "Half-precision / 4-bit".to_owned(),
                        false,
                    ),
                    size_tile(
                        "MEMORY TO TRAIN",
                        format_size_mb(sz.peak_train_ram_mb),
                        format!("Full folder: {}", format_size_mb(sz.full_run_folder_mb)),
                        false,
                    ),
                ]
                .spacing(10),
            ]
            .spacing(10),
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
        .into()
    } else {
        container(
            column![
                row![
                    text("MODEL FILE SIZE & RUNTIME MEMORY PREDICTOR")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    text(format!(
                        "Total: {} params ({} active/token)",
                        format_count(sz.total_params),
                        format_count(sz.active_params)
                    ))
                    .size(11.5)
                    .font(style::LABEL)
                    .color(style::OK),
                ]
                .align_y(Center),
                row![
                    size_tile(
                        "FP32 SAFETENSORS",
                        format_size_mb(sz.fp32_safetensors_mb),
                        "Exact 32-bit checkpoint".to_owned(),
                        true,
                    ),
                    size_tile(
                        "BF16 / FP16 SIZE",
                        format_size_mb(sz.fp16_bf16_mb),
                        "16-bit export size".to_owned(),
                        false,
                    ),
                    size_tile(
                        "INT8 / INT4 QUANT",
                        format!(
                            "{} / {}",
                            format_size_mb(sz.int8_quant_mb),
                            format_size_mb(sz.int4_quant_mb)
                        ),
                        "8-bit & 4-bit edge size".to_owned(),
                        false,
                    ),
                    size_tile(
                        "PEAK TRAIN / CHAT RAM",
                        format!(
                            "{} / {}",
                            format_size_mb(sz.peak_train_ram_mb),
                            format_size_mb(sz.chat_fp32_ram_mb)
                        ),
                        format!("Run folder: {}", format_size_mb(sz.full_run_folder_mb)),
                        false,
                    ),
                ]
                .spacing(10),
            ]
            .spacing(10),
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
        .into()
    };

    // 2. Interactive Parameter-to-Token Ratio Adjuster Card
    let mut ratio_presets = row![].spacing(7);
    let presets: &[(f64, &str)] = if simple {
        &[
            (2.0, "Quick Test (2×)"),
            (20.0, "Recommended Optimal (20×)"),
            (40.0, "Extra Thorough (40×)"),
        ]
    } else {
        &[
            (2.0, "2× Smoke"),
            (10.0, "10× Draft"),
            (20.0, "20× Chinchilla"),
            (40.0, "40× Llama"),
            (80.0, "80× Deep"),
        ]
    };

    for &(target_r, lbl) in presets {
        let near = (ratio.tokens_per_param - target_r).abs() < (target_r * 0.18).max(0.8);
        ratio_presets = ratio_presets.push(
            button(text(lbl).size(11.5).font(style::LABEL))
                .padding([6, 12])
                .on_press(Message::ApplyTokensPerParamRatio(target_r))
                .style(move |t, s| style::mini_toggle(near, t, s)),
        );
    }
    ratio_presets = ratio_presets.push(
        button(
            text(if simple {
                "Auto-Size AI to My Text"
            } else {
                "Auto-Size Model to Dataset"
            })
            .size(11.5)
            .font(style::STRONG),
        )
        .padding([6, 13])
        .on_press(Message::AutoSizeModelToDataset)
        .style(style::control_button),
    );

    let fine_adjust_row: Element<'_, Message> = if simple {
        space().height(0).into()
    } else {
        row![
            mini_stepper(
                "TOKENS / PARAM STEPPER",
                format!("{:.1}×", ratio.tokens_per_param),
                Message::AdjustTokensPerParamRatio(-2.0),
                Message::AdjustTokensPerParamRatio(2.0),
            ),
            container(
                column![
                    text("TARGET TOKENS / PARAM")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    text_input("20.0", &app.target_ratio_input)
                        .on_input(Message::EditTokensPerParamRatio)
                        .padding([7, 10])
                        .size(13)
                        .style(style::composer_input),
                ]
                .spacing(6),
            )
            .width(FillPortion(1))
            .padding(12)
            .style(style::card),
            container(
                column![
                    text("SCHEDULED TOKENS")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    text(format!(
                        "{} ({} steps)",
                        format_count(ratio.scheduled_tokens),
                        app.cfg.hyper.total_steps
                    ))
                    .size(13)
                    .font(style::LABEL)
                    .color(style::WHITE),
                ]
                .spacing(6),
            )
            .width(FillPortion(1))
            .padding(12)
            .style(style::card),
        ]
        .spacing(10)
        .into()
    };

    let ratio_card = container(
        column![
            row![
                column![
                    text(if simple {
                        "TRAINING BALANCE (TEXT TOKENS PER PARAMETER)"
                    } else {
                        "PARAMETER-TO-TOKEN RATIO ADJUSTER (CHINCHILLA SCALING)"
                    })
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                    text(format!(
                        "{:.1} tokens per parameter · {} total training tokens",
                        ratio.tokens_per_param,
                        format_count(ratio.scheduled_tokens)
                    ))
                    .size(15)
                    .font(style::STRONG)
                    .color(style::WHITE),
                ]
                .spacing(3)
                .width(Fill),
                container(
                    text(ratio.status_badge)
                        .size(11)
                        .font(style::LABEL)
                        .color(if ratio.is_balanced {
                            style::OK
                        } else {
                            style::DANGER
                        }),
                )
                .padding([4, 10])
                .style(style::badge),
            ]
            .align_y(Center),
            text(ratio.plain_advice).size(12).color(style::GREY),
            ratio_presets,
            fine_adjust_row,
        ]
        .spacing(10),
    )
    .width(Fill)
    .padding(18)
    .style(style::card);

    column![size_card, ratio_card].spacing(16).into()
}

// ============================================================================
// STAGE 02: TOKENIZER VIEW (SIMPLE -> NORMAL -> ADVANCED)
// ============================================================================

pub fn stage_tokenizer_deep_view(app: &App) -> Element<'_, Message> {
    let tk_cfg = &app.cfg.tokenizer;
    let level = app.ui_complexity;

    // Active tokenizer token chips (capped cleanly so it never floods the screen)
    let max_chips = if level == UiComplexity::Simple { 24 } else { 42 };
    let mut token_badges = column![].spacing(6);
    let mut current_line = row![].spacing(6);
    let mut line_chars = 0usize;
    for (id, disp) in app.tokenizer_preview.tokens.iter().take(max_chips) {
        let label = if level == UiComplexity::Simple {
            disp.clone()
        } else {
            format!("{disp} #{id}")
        };
        line_chars += label.chars().count() + 3;
        current_line = current_line.push(
            container(text(label).size(11.5).font(style::LABEL).color(style::TEXT_2))
                .padding([4, 9])
                .style(style::badge),
        );
        if line_chars > 64 {
            token_badges = token_badges.push(current_line);
            current_line = row![].spacing(6);
            line_chars = 0;
        }
    }
    if line_chars > 0 {
        token_badges = token_badges.push(current_line);
    }

    // --- SIMPLE MODE: Calm, plain-English 2-card view ---
    if level == UiComplexity::Simple {
        let friendly_desc = match tk_cfg.kind {
            TokenizerKind::ByteLevelBpe => {
                "Smart Subwords (Recommended): Splits common words whole and rare words into smaller pieces. Works on any language, code, or emoji with zero unknown words."
            }
            TokenizerKind::WordPiece => {
                "Word-Piece: Keeps everyday words intact and marks word endings with '##' (the classic BERT style)."
            }
            TokenizerKind::Unigram => {
                "Probabilistic Subwords: Picks the most likely word pieces statistically — great for multilingual text."
            }
            TokenizerKind::CharLevel => {
                "Character-by-Character: Reads one letter at a time. Tiny vocabulary, best for small toy experiments."
            }
            TokenizerKind::PretrainedFile => {
                "Custom File: Uses an existing Hugging Face tokenizer.json file from your computer."
            }
        };

        let mut simple_pills = row![].spacing(8);
        for (kind, friendly_lbl) in [
            (TokenizerKind::ByteLevelBpe, "Smart Subwords (Recommended)"),
            (TokenizerKind::WordPiece, "Word-Piece"),
            (TokenizerKind::Unigram, "Probabilistic"),
            (TokenizerKind::CharLevel, "Letter-by-Letter"),
        ] {
            let active = tk_cfg.kind == kind;
            simple_pills = simple_pills.push(
                button(text(friendly_lbl).size(12).font(style::LABEL))
                    .padding([7, 14])
                    .on_press(Message::SelectTokenizerKind(kind))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }

        return column![
            eyebrow_header(
                "STEP 2 OF 6 · VOCABULARY",
                "How Should Your AI Read Words?",
                "Before an AI can learn from text, it breaks sentences into bite-sized pieces called tokens."
            ),
            container(
                column![
                    text("CHOOSE READING STYLE")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    simple_pills,
                    container(text(friendly_desc).size(12.5).color(style::TEXT_2))
                        .width(Fill)
                        .padding(13)
                        .style(style::surface),
                ]
                .spacing(12)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            container(
                column![
                    row![
                        text("TRY A SAMPLE SENTENCE")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM)
                            .width(Fill),
                        text(format!(
                            "{} pieces · {} vocabulary size",
                            app.tokenizer_preview.tokens.len(),
                            app.tokenizer
                                .as_ref()
                                .map(|t| t.vocab_size())
                                .unwrap_or(tk_cfg.vocab_size)
                        ))
                        .size(11.5)
                        .color(style::OK),
                    ]
                    .align_y(Center),
                    text_input("Type a sentence to see how the AI splits it…", &app.tokenizer_sample)
                        .on_input(Message::EditTokenizerSample)
                        .padding([9, 12])
                        .size(13)
                        .style(style::composer_input),
                    token_badges,
                    row![
                        button(
                            text("Rebuild Vocabulary")
                                .size(12)
                                .font(style::LABEL)
                        )
                        .padding([8, 14])
                        .on_press(Message::BuildTokenizer)
                        .style(style::control_button),
                        space().width(Fill),
                        button(
                            text("Next: Choose AI Brain Size  →")
                                .size(12.5)
                                .font(style::STRONG)
                                .color(style::BLACK)
                        )
                        .padding([9, 16])
                        .on_press(Message::SelectStage(PipelineStage::Architecture))
                        .style(style::primary_button),
                    ]
                    .spacing(10)
                    .align_y(Center),
                ]
                .spacing(11)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            mode_upsell_footer(level),
        ]
        .spacing(16)
        .into();
    }

    // --- NORMAL & ADVANCED MODES ---
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

    let guide_block: Element<'_, Message> = if level == UiComplexity::Expert {
        let guide_kv = |label: &'static str, body: &'static str| -> Element<'static, Message> {
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
        };
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
            .spacing(6),
        )
        .width(Fill)
        .padding(13)
        .style(style::surface)
        .into()
    } else {
        container(
            column![
                text(guide.subtitle)
                    .size(12.5)
                    .font(style::STRONG)
                    .color(style::WHITE),
                text(guide.mechanism).size(12).color(style::GREY),
            ]
            .spacing(4),
        )
        .width(Fill)
        .padding(12)
        .style(style::surface)
        .into()
    };

    // Expert pre-tokenization card (only in Expert mode!)
    let expert_rules_card: Element<'_, Message> = if level == UiComplexity::Expert {
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
        container(
            column![
                text("ADVANCED PRE-TOKENIZATION, MATH DIGIT SPLITTING & TILE ALIGNMENT")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                column![text("Boundary splitting rule").size(11.5).color(style::GREY), pre_pills].spacing(5),
                column![text("Number & arithmetic digit policy").size(11.5).color(style::GREY), digit_pills].spacing(5),
                column![text("Unicode normalization").size(11.5).color(style::GREY), norm_pills].spacing(5),
                column![text("Hardware vocabulary tile alignment").size(11.5).color(style::GREY), pad_pills].spacing(5),
                row![
                    mini_stepper(
                        "SUBWORD DROPOUT",
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
                    "Decomposes unseen Unicode characters into hex byte tokens in WordPiece/Unigram for 0% <unk>.",
                    tk_cfg.byte_fallback,
                    Message::ToggleByteFallback
                ),
            ]
            .spacing(10),
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
        .into()
    } else {
        space().height(0).into()
    };

    // 4-way Arena comparison table
    let mut arena_rows = column![].spacing(7);
    for row_data in &app.tokenizer_arena {
        let is_selected = row_data.kind == tk_cfg.kind;
        arena_rows = arena_rows.push(
            container(
                row![
                    text(format!(
                        "{}{}",
                        row_data.kind.label(),
                        if is_selected { " · ACTIVE" } else { "" }
                    ))
                    .size(12)
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
                    text(format!("~{} words/ctx", row_data.est_words_per_ctx))
                        .size(11.5)
                        .color(style::OK)
                        .width(FillPortion(1)),
                    button(text("Select").size(10.5).font(style::LABEL))
                        .padding([4, 10])
                        .on_press(Message::SelectTokenizerKind(row_data.kind))
                        .style(move |t, s| style::mini_toggle(is_selected, t, s)),
                ]
                .spacing(8)
                .align_y(Center),
            )
            .width(Fill)
            .padding(10)
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
            "STAGE 02 / TOKENIZER & VOCABULARY",
            "Choose & Compare Subword Tokenizers",
            "Pick a subword algorithm, set vocabulary size, and compare compression across your dataset."
        ),
        container(
            column![
                row![
                    text("TOKENIZER ALGORITHM")
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
                guide_block,
                vocab_or_file,
                switch_row(
                    "Sequence packing",
                    "Packs documents back-to-back with <bos>/<eos> separators so zero compute is wasted on padding.",
                    tk_cfg.sequence_packing,
                    Message::ToggleSequencePacking
                ),
                row![
                    button(
                        text("Train / Rebuild Tokenizer")
                            .size(12.5)
                            .font(style::STRONG)
                            .color(style::BLACK)
                    )
                    .padding([9, 16])
                    .on_press(Message::BuildTokenizer)
                    .style(style::primary_button),
                    text(tk_summary).size(12).color(style::OK).width(Fill),
                    button(text("Next: 03 Model  →").size(12).font(style::LABEL))
                        .padding([9, 15])
                        .on_press(Message::SelectStage(PipelineStage::Architecture))
                        .style(style::control_button)
                ]
                .spacing(12)
                .align_y(Center),
            ]
            .spacing(12)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        expert_rules_card,
        container(
            column![
                row![
                    text("LIVE PROBE & 4-TOKENIZER COMPARISON")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(text("Refresh 4-Way Comparison").size(11).font(style::LABEL))
                        .padding([5, 11])
                        .on_press(Message::RunTokenizerArena)
                        .style(style::control_button)
                ]
                .align_y(Center),
                text_input("Type prose, math, or code to inspect splits…", &app.tokenizer_sample)
                    .on_input(Message::EditTokenizerSample)
                    .padding([9, 12])
                    .size(13)
                    .style(style::composer_input),
                token_badges,
                arena_rows,
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        mode_upsell_footer(level),
    ]
    .spacing(16)
    .into()
}

// ============================================================================
// EXTRA TRANSFORMER ENGINE #1 CONTROLS (EXPERT MODE ONLY IN STAGE 03)
// ============================================================================

pub fn transformer_advanced_card(app: &App) -> Element<'_, Message> {
    if app.ui_complexity != UiComplexity::Expert {
        return space().height(0).into();
    }
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
                    "ATTN LOGIT SOFTCAP",
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
// STAGE 04: HARDWARE, POPULAR GPU/CPU SIMULATOR & AUTO-OPTIMIZER
// ============================================================================

pub fn stage_hardware_view(app: &App) -> Element<'_, Message> {
    let hw = &app.hardware;
    let exec = &app.cfg.hardware_exec;
    let plan = &app.optimization_plan;
    let ps = &plan.summary;
    let level = app.ui_complexity;

    let gpu_headline = hw
        .best_hardware_gpu()
        .map(|g| format!("{} ({} MB max buffer)", g.name, g.max_buffer_mb))
        .unwrap_or_else(|| "Integrated / CPU SIMD (No separate discrete GPU required)".to_owned());

    // --- SIMPLE MODE: Calm, reassuring 2-card view ---
    if level == UiComplexity::Simple {
        let mut simple_targets = row![].spacing(8);
        for (t_opt, friendly_lbl) in [
            (ComputeTarget::Auto, "Automatic · Best Speed (Recommended)"),
            (ComputeTarget::Cpu, "Processor (CPU)"),
            (ComputeTarget::Gpu, "Graphics Card (GPU)"),
        ] {
            let active = exec.target == t_opt;
            simple_targets = simple_targets.push(
                button(text(friendly_lbl).size(12).font(style::LABEL))
                    .padding([7, 14])
                    .on_press(Message::SelectComputeTarget(t_opt))
                    .style(move |t, s| style::mini_toggle(active, t, s)),
            );
        }

        let fit_msg = if ps.fits_in_budget {
            format!(
                "Fits comfortably on your computer — uses {} out of {:.1} GB safe memory ({:.0}% free headroom).",
                format_size_mb(ps.estimated_peak_mb),
                ps.device_budget_mb / 1024.0,
                ps.headroom_pct
            )
        } else {
            format!(
                "Model needs {} which is tight for {:.1} GB budget — click 'Auto-Tune for My PC' below to fit safely.",
                format_size_mb(ps.estimated_peak_mb),
                ps.device_budget_mb / 1024.0
            )
        };

        return column![
            eyebrow_header(
                "STEP 4 OF 6 · YOUR COMPUTER",
                "Computer Check & Automatic Speed Tuning",
                "We checked your processor, memory, and graphics card automatically — no drivers or Python setup needed."
            ),
            container(
                column![
                    row![
                        text("YOUR DETECTED HARDWARE")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM)
                            .width(Fill),
                        button(text("Refresh Hardware").size(11).font(style::LABEL))
                            .padding([5, 11])
                            .on_press(Message::RescanHardware)
                            .style(style::tiny_button),
                    ]
                    .align_y(Center),
                    row![
                        size_tile(
                            "PROCESSOR (CPU)",
                            format!("{} Cores", hw.cpu.logical_cores),
                            hw.cpu.brand.clone(),
                            false,
                        ),
                        size_tile(
                            "SYSTEM MEMORY (RAM)",
                            format!("{:.1} GB Available", hw.memory.available_ram_mb as f64 / 1024.0),
                            format!("{:.1} GB Total RAM", hw.memory.total_ram_mb as f64 / 1024.0),
                            true,
                        ),
                        size_tile(
                            "GRAPHICS CARD (GPU)",
                            if hw.best_hardware_gpu().is_some() {
                                "Ready".to_owned()
                            } else {
                                "CPU Mode".to_owned()
                            },
                            gpu_headline,
                            hw.best_hardware_gpu().is_some(),
                        ),
                    ]
                    .spacing(10),
                    container(
                        text(fit_msg)
                            .size(12.5)
                            .color(if ps.fits_in_budget { style::OK } else { style::DANGER })
                    )
                    .width(Fill)
                    .padding(12)
                    .style(style::surface),
                ]
                .spacing(12)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            container(
                column![
                    text("CHOOSE WHERE TO TRAIN")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    simple_targets,
                    row![
                        button(
                            text("Auto-Tune Best Speed for My PC")
                                .size(12.5)
                                .font(style::STRONG)
                                .color(style::BLACK)
                        )
                        .padding([9, 16])
                        .on_press(Message::ApplyHardwareOptimizationPlan)
                        .style(style::primary_button),
                        space().width(Fill),
                        button(text("Next: Save & Repeatability  →").size(12).font(style::LABEL))
                            .padding([9, 15])
                            .on_press(Message::SelectStage(PipelineStage::Repro))
                            .style(style::control_button),
                    ]
                    .spacing(10)
                    .align_y(Center),
                ]
                .spacing(12)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            mode_upsell_footer(level),
        ]
        .spacing(16)
        .into();
    }

    // --- NORMAL & ADVANCED MODES ---
    let mut hw_preset_row1 = row![].spacing(6);
    let mut hw_preset_row2 = row![].spacing(6);
    for (idx, preset) in ReferenceHardwarePreset::ALL.iter().copied().enumerate() {
        let active = app.hw_preset == preset;
        let btn = button(text(preset.label()).size(11).font(style::LABEL))
            .padding([5, 10])
            .on_press(Message::SelectReferenceHardwarePreset(preset))
            .style(move |t, s| style::mini_toggle(active, t, s));
        if idx < 5 {
            hw_preset_row1 = hw_preset_row1.push(btn);
        } else {
            hw_preset_row2 = hw_preset_row2.push(btn);
        }
    }

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

    let mut rationale_col = column![].spacing(5);
    let max_notes = if level == UiComplexity::Expert { 10 } else { 4 };
    for (idx, item) in plan.rationale.iter().take(max_notes).enumerate() {
        rationale_col = rationale_col.push(
            text(format!("{}. {item}", idx + 1))
                .size(12)
                .color(style::TEXT_2),
        );
    }

    let expert_hw_extras: Element<'_, Message> = if level == UiComplexity::Expert {
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
                        text(format!("Winner: {}", b.recommended_winner))
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
                ]
                .spacing(4),
            )
            .width(Fill)
            .padding(12)
            .style(style::surface)
            .into()
        } else {
            space().height(0).into()
        };

        container(
            column![
                row![
                    text("EXPERT MEMORY GUARDS, KERNEL BENCHMARK & GENERATED SCRIPT")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(
                        text("Run 256×256 CPU vs WGSL GPU Benchmark")
                            .size(11)
                            .font(style::STRONG)
                    )
                    .padding([5, 11])
                    .on_press(Message::RunComputeBenchmark)
                    .style(style::control_button),
                    button(text("Export Plan (.toml)").size(11).font(style::LABEL))
                        .padding([5, 11])
                        .on_press(Message::ExportOptimizationScript)
                        .style(style::control_button),
                ]
                .spacing(8)
                .align_y(Center),
                switch_row(
                    "Low-memory micro-batch slicing & activation checkpointing",
                    "Splits micro-batches with immediate per-slice backward() so peak activation RAM drops by ~2×.",
                    exec.activation_checkpointing,
                    Message::ToggleActivationCheckpointing
                ),
                switch_row(
                    "Pad tokenizer vocabulary to hardware tile multiple (64× CPU / 128× GPU)",
                    "Aligns embedding & LM-head dimensions to SIMD/GPU tile boundaries.",
                    exec.pad_vocab_for_hardware,
                    Message::ToggleHardwareVocabPad
                ),
                bench_block,
                container(
                    scrollable(
                        text(plan.custom_script_toml.clone())
                            .size(11.5)
                            .color(style::TEXT_2)
                    )
                    .height(155)
                    .style(style::quiet_scroll)
                )
                .width(Fill)
                .padding(12)
                .style(style::surface),
            ]
            .spacing(10),
        )
        .width(Fill)
        .padding(18)
        .style(style::card)
        .into()
    } else {
        space().height(0).into()
    };

    column![
        eyebrow_header(
            "STAGE 04 / HARDWARE, POPULAR GPU/CPU SIMULATOR & AUTO-OPTIMIZER",
            "System Hardware, Target Simulator & Custom Plan",
            "Tune for your live PC or test how your model fits and optimizes across popular consumer GPUs & CPUs."
        ),
        container(
            column![
                row![
                    text("ACTIVE HARDWARE PROFILE & POPULAR GPU / CPU SIMULATOR")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM)
                        .width(Fill),
                    button(text("Rescan Live PC").size(11).font(style::LABEL))
                        .padding([5, 11])
                        .on_press(Message::RescanHardware)
                        .style(style::tiny_button),
                ]
                .align_y(Center),
                hw_preset_row1,
                hw_preset_row2,
                row![
                    size_tile(
                        "ACTIVE CPU & SIMD",
                        format!("{}C · {}", hw.cpu.logical_cores, hw.cpu.simd_tier()),
                        hw.cpu.brand.clone(),
                        false,
                    ),
                    size_tile(
                        "SYSTEM RAM",
                        format!("{:.1} GB Free", hw.memory.available_ram_mb as f64 / 1024.0),
                        format!("{:.1} GB Total", hw.memory.total_ram_mb as f64 / 1024.0),
                        true,
                    ),
                    size_tile(
                        "ACTIVE GPU ADAPTER",
                        hw.best_hardware_gpu()
                            .map(|g| g.backend.clone())
                            .unwrap_or_else(|| "CPU SIMD".to_owned()),
                        gpu_headline,
                        hw.best_hardware_gpu().is_some(),
                    ),
                ]
                .spacing(10),
            ]
            .spacing(10)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        container(
            column![
                row![
                    column![
                        text("DEVICE TARGET & CUSTOM OPTIMIZATION PLAN")
                            .size(10.5)
                            .font(style::LABEL)
                            .color(style::DIM),
                        text(format!(
                            "{} · Peak {} / {:.1} GB budget ({:.0}% free)",
                            ps.resolved_device_label,
                            format_size_mb(ps.estimated_peak_mb),
                            ps.device_budget_mb / 1024.0,
                            ps.headroom_pct
                        ))
                        .size(13.5)
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
                ]
                .align_y(Center),
                target_pills,
                prec_pills,
                row![
                    mini_stepper(
                        "CPU THREADS",
                        app.cfg.hyper.compute_threads.to_string(),
                        Message::AdjustComputeThreads(-1),
                        Message::AdjustComputeThreads(1)
                    ),
                    mini_stepper(
                        "MICRO-BATCH",
                        app.cfg.hyper.batch_size.to_string(),
                        Message::AdjustBatchSize(-1),
                        Message::AdjustBatchSize(1)
                    ),
                    mini_stepper(
                        "GRAD ACCUM (RAM SAVER)",
                        format!("{}×", app.cfg.hyper.grad_accum_steps),
                        Message::AdjustGradAccum(-1),
                        Message::AdjustGradAccum(1)
                    ),
                ]
                .spacing(10),
                container(rationale_col)
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
        .style(style::card),
        expert_hw_extras,
        mode_upsell_footer(level),
    ]
    .spacing(16)
    .into()
}

// ============================================================================
// STAGE 05: SEED, PROVENANCE & INITIAL RANDOM STATE (SIMPLE -> NORMAL -> EXPERT)
// ============================================================================

pub fn stage_repro_view(app: &App) -> Element<'_, Message> {
    let seeds = &app.cfg.seeds;
    let level = app.ui_complexity;

    // --- SIMPLE MODE: Clean 2-card view ---
    if level == UiComplexity::Simple {
        return column![
            eyebrow_header(
                "STEP 5 OF 6 · SAVE & REPEATABILITY",
                "Repeatability Seed & Saving Your Setup",
                "Keeping the same seed number lets you recreate the exact same starting AI anytime, even on another computer."
            ),
            container(
                column![
                    text("STARTING SEED NUMBER")
                        .size(10.5)
                        .font(style::LABEL)
                        .color(style::DIM),
                    row![
                        text_input("42", &app.seed_input)
                            .on_input(Message::EditMasterSeed)
                            .padding([9, 12])
                            .size(14)
                            .width(220)
                            .style(style::composer_input),
                        button(text("Pick a Random Number").size(12).font(style::LABEL))
                            .padding([9, 14])
                            .on_press(Message::RandomizeSeed)
                            .style(style::control_button),
                    ]
                    .spacing(10)
                    .align_y(Center),
                    text("Tip: Seed 42 is a classic default. Change it anytime to try a fresh random starting brain.")
                        .size(12)
                        .color(style::GREY),
                ]
                .spacing(10)
            )
            .width(Fill)
            .padding(18)
            .style(style::card),
            container(
                column![
                    switch_row(
                        "Save untouched starting AI weights before training begins",
                        "Archives the initial random brain (genesis_step0.safetensors) alongside your trained model.",
                        seeds.auto_export_genesis_init,
                        Message::ToggleAutoExportGenesis
                    ),
                    row![
                        button(
                            text("Export Settings & Hardware Summary")
                                .size(12)
                                .font(style::LABEL)
                        )
                        .padding([9, 14])
                        .on_press(Message::ExportProvenanceBundle {
                            include_genesis_weights: false
                        })
                        .style(style::control_button),
                        button(
                            text("Export Settings + Starting Random Brain")
                                .size(12)
                                .font(style::LABEL)
                        )
                        .padding([9, 14])
                        .on_press(Message::ExportProvenanceBundle {
                            include_genesis_weights: true
                        })
                        .style(style::control_button),
                        space().width(Fill),
                        button(
                            text("Next: Start Training  →")
                                .size(12.5)
                                .font(style::STRONG)
                                .color(style::BLACK)
                        )
                        .padding([9, 16])
                        .on_press(Message::SelectStage(PipelineStage::Train))
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
            mode_upsell_footer(level),
        ]
        .spacing(16)
        .into();
    }

    // --- NORMAL & EXPERT MODES ---
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

    let subsystem_seeds_block: Element<'_, Message> = if level == UiComplexity::Expert {
        column![
            switch_row(
                "Lock subsystem seeds to Master Seed (domain-separated derivation)",
                "Derives collision-free streams for Weight Init, Data Shuffle, Dropout/MoE, and Sampling from Master Seed.",
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
        .spacing(10)
        .into()
    } else {
        space().height(0).into()
    };

    let genesis_inspector: Element<'_, Message> = if level == UiComplexity::Expert {
        if let Some(rep) = &app.genesis_report {
            let floats_preview = rep
                .first_16_embedding_floats
                .iter()
                .take(10)
                .map(|v| format!("{v:+.5}"))
                .collect::<Vec<_>>()
                .join(", ");
            let mut tensor_rows = column![].spacing(4);
            for st in rep.tensor_stats.iter().take(6) {
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
                    ]
                    .spacing(8)
                    .align_y(Center),
                );
            }
            container(
                column![
                    row![
                        text("STEP-0 INITIAL RANDOM-FILLED TENSOR INSPECTOR")
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
                                "{} tensors ({} params) · mean {:+.5} · std {:.5} · tok_embeddings[0..10] = [{floats_preview}, …]",
                                rep.total_tensors,
                                format_count(rep.total_params),
                                rep.global_mean,
                                rep.global_std,
                            ))
                            .size(11.5)
                            .color(style::TEXT_2),
                        ]
                        .spacing(4)
                    )
                    .width(Fill)
                    .padding(12)
                    .style(style::surface),
                    container(tensor_rows)
                        .width(Fill)
                        .padding(11)
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
        }
    } else {
        space().height(0).into()
    };

    column![
        eyebrow_header(
            "STAGE 05 / DETERMINISTIC SEEDS, HARDWARE PROVENANCE & GENESIS STATE",
            "Seeds, Provenance & Initial Random State Export",
            "Set deterministic seeds, export settings + hardware provenance, and archive or reload step-0 random weights."
        ),
        container(
            column![
                text("PORTABLE PRNG ENGINE & MASTER SEED")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                algo_pills,
                row![
                    text_input("42", &app.seed_input)
                        .on_input(Message::EditMasterSeed)
                        .padding([8, 11])
                        .size(13)
                        .width(240)
                        .style(style::composer_input),
                    button(text("Roll Entropy Seed").size(11.5).font(style::LABEL))
                        .padding([8, 13])
                        .on_press(Message::RandomizeSeed)
                        .style(style::control_button),
                ]
                .spacing(8)
                .align_y(Center),
                subsystem_seeds_block,
            ]
            .spacing(11)
        )
        .width(Fill)
        .padding(18)
        .style(style::card),
        container(
            column![
                text("PROVENANCE & INITIAL RANDOM-FILLED STATE (GENESIS SAFETENSORS)")
                    .size(10.5)
                    .font(style::LABEL)
                    .color(style::DIM),
                switch_row(
                    "Archive initial random-filled state (genesis_step0.safetensors) when training starts",
                    "Writes the exact untouched step-0 random tensors + SHA-256 manifest before gradient step 1.",
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
        genesis_inspector,
        mode_upsell_footer(level),
    ]
    .spacing(16)
    .into()
}
