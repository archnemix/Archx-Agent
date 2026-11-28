//! Purpose: Generates font-free pure-Rust SVG vector charts (`svg::Handle`) matching Archx AI Lab's black-and-silver design system.

use std::fmt::Write as _;

use iced::widget::svg;

use crate::config::{Routing, TransformerConfig};
use crate::telemetry::StepPoint;

/// Renders training loss (white) and validation loss (emerald) curves.
pub fn loss_chart_svg(points: &[StepPoint], log_scale: bool) -> svg::Handle {
    let (w, h, pad) = (560.0f32, 176.0f32, 14.0f32);
    let mut out = svg_header(w, h);
    draw_grid(&mut out, w, h, pad, 4);

    if points.is_empty() {
        let mid = h * 0.5;
        let _ = writeln!(
            out,
            r#"<line x1="{pad}" y1="{mid:.1}" x2="{:.1}" y2="{mid:.1}" stroke="#404040" stroke-width="1.5" stroke-dasharray="5,5"/>"#,
            w - pad
        );
        out.push_str("</svg>");
        return svg::Handle::from_memory(out.into_bytes());
    }

    let transform = |v: f32| -> f32 {
        let clamped = v.max(1e-4);
        if log_scale { clamped.ln() } else { clamped }
    };

    let mut min_y = f32::INFINITY;
    let mut max_y = f32::NEG_INFINITY;
    for p in points {
        if p.train_loss.is_finite() {
            let y = transform(p.train_loss);
            min_y = min_y.min(y);
            max_y = max_y.max(y);
        }
        if let Some(vl) = p.val_loss {
            if vl.is_finite() {
                let y = transform(vl);
                min_y = min_y.min(y);
                max_y = max_y.max(y);
            }
        }
    }
    if !min_y.is_finite() || !max_y.is_finite() {
        min_y = 0.0;
        max_y = 1.0;
    }
    let span_y = (max_y - min_y).max(1e-3);
    let max_step = points.last().map(|p| p.step.max(1)).unwrap_or(1) as f32;
    let min_step = points.first().map(|p| p.step).unwrap_or(0) as f32;
    let span_x = (max_step - min_step).max(1.0);

    let map_xy = |step: usize, val: f32| -> (f32, f32) {
        let x = pad + ((step as f32 - min_step) / span_x) * (w - 2.0 * pad);
        let norm_y = (transform(val) - min_y) / span_y;
        let y = (h - pad) - norm_y * (h - 2.0 * pad);
        (x, y)
    };

    // Train loss polyline (#f4f4f4)
    let mut train_pts = String::new();
    for p in points {
        if p.train_loss.is_finite() {
            let (x, y) = map_xy(p.step, p.train_loss);
            let _ = write!(train_pts, "{x:.1},{y:.1} ");
        }
    }
    if !train_pts.is_empty() {
        let _ = writeln!(
            out,
            r#"<polyline fill="none" stroke="#f4f4f4" stroke-width="2.0" stroke-linejoin="round" stroke-linecap="round" points="{train_pts}"/>"#
        );
    }

    // Validation loss polyline + markers (#22c55e)
    let mut val_pts = String::new();
    let mut val_dots = String::new();
    for p in points {
        if let Some(vl) = p.val_loss {
            if vl.is_finite() {
                let (x, y) = map_xy(p.step, vl);
                let _ = write!(val_pts, "{x:.1},{y:.1} ");
                let _ = writeln!(
                    val_dots,
                    r#"<circle cx="{x:.1}" cy="{y:.1}" r="3.0" fill="#22c55e"/>"#
                );
            }
        }
    }
    if !val_pts.is_empty() {
        let _ = writeln!(
            out,
            r#"<polyline fill="none" stroke="#22c55e" stroke-width="1.8" points="{val_pts}"/>"#
        );
        out.push_str(&val_dots);
    }

    out.push_str("</svg>");
    svg::Handle::from_memory(out.into_bytes())
}

/// Renders learning-rate schedule (amber) and gradient L2 norm (silver) curves.
pub fn lr_grad_chart_svg(points: &[StepPoint]) -> svg::Handle {
    let (w, h, pad) = (560.0f32, 118.0f32, 12.0f32);
    let mut out = svg_header(w, h);
    draw_grid(&mut out, w, h, pad, 3);

    if points.len() >= 2 {
        let min_step = points.first().map(|p| p.step).unwrap_or(0) as f32;
        let max_step = points.last().map(|p| p.step.max(1)).unwrap_or(1) as f32;
        let span_x = (max_step - min_step).max(1.0);

        let max_lr = points
            .iter()
            .map(|p| p.lr as f32)
            .fold(1e-8f32, f32::max);
        let max_grad = points
            .iter()
            .filter(|p| p.grad_norm.is_finite())
            .map(|p| p.grad_norm)
            .fold(1e-4f32, f32::max);

        let mut lr_pts = String::new();
        let mut grad_pts = String::new();
        for p in points {
            let x = pad + ((p.step as f32 - min_step) / span_x) * (w - 2.0 * pad);
            let y_lr = (h - pad) - ((p.lr as f32) / max_lr).clamp(0.0, 1.0) * (h - 2.0 * pad);
            let _ = write!(lr_pts, "{x:.1},{y_lr:.1} ");
            if p.grad_norm.is_finite() {
                let y_g = (h - pad) - (p.grad_norm / max_grad).clamp(0.0, 1.0) * (h - 2.0 * pad);
                let _ = write!(grad_pts, "{x:.1},{y_g:.1} ");
            }
        }
        let _ = writeln!(
            out,
            r#"<polyline fill="none" stroke="#8a8a8a" stroke-width="1.5" points="{grad_pts}"/>"#
        );
        let _ = writeln!(
            out,
            r#"<polyline fill="none" stroke="#eab308" stroke-width="1.8" points="{lr_pts}"/>"#
        );
    }

    out.push_str("</svg>");
    svg::Handle::from_memory(out.into_bytes())
}

/// Renders a 16×16 diverging neural matrix tile (`[-1.0, 1.0]`):
/// negative values in cool slate/blue-silver, zero in `#121212`, positive in crisp white/emerald.
pub fn heatmap_16x16_svg(tile: &[f32], emerald_tint: bool) -> svg::Handle {
    let size = 208.0f32;
    let cell = size / 16.0;
    let mut out = svg_header(size, size);
    for r in 0..16 {
        for c in 0..16 {
            let v = tile.get(r * 16 + c).copied().unwrap_or(0.0).clamp(-1.0, 1.0);
            let (red, green, blue) = if v >= 0.0 {
                let t = v;
                if emerald_tint {
                    (
                        (18.0 + t * (34.0 - 18.0)) as u8,
                        (18.0 + t * (197.0 - 18.0)) as u8,
                        (18.0 + t * (94.0 - 18.0)) as u8,
                    )
                } else {
                    let shade = (18.0 + t * 226.0) as u8;
                    (shade, shade, shade)
                }
            } else {
                let t = -v;
                (
                    (18.0 + t * (239.0 - 18.0) * 0.65) as u8,
                    (18.0 + t * 44.0) as u8,
                    (18.0 + t * 92.0) as u8,
                )
            };
            let x = c as f32 * cell;
            let y = r as f32 * cell;
            let _ = writeln!(
                out,
                r#"<rect x="{x:.2}" y="{y:.2}" width="{:.2}" height="{:.2}" fill="#{red:02x}{green:02x}{blue:02x}"/>"#,
                cell - 0.8,
                cell - 0.8
            );
        }
    }
    out.push_str("</svg>");
    svg::Handle::from_memory(out.into_bytes())
}

/// Renders the MoE per-expert routing load bar chart with an ideal uniform reference line.
pub fn moe_load_svg(loads_pct: &[f32]) -> svg::Handle {
    let (w, h, pad) = (440.0f32, 120.0f32, 12.0f32);
    let mut out = svg_header(w, h);
    draw_grid(&mut out, w, h, pad, 2);

    if !loads_pct.is_empty() {
        let n = loads_pct.len();
        let ideal = 100.0 / (n as f32);
        let max_v = loads_pct.iter().copied().fold(ideal * 2.0, f32::max).max(1.0);
        let inner_w = w - 2.0 * pad;
        let slot_w = inner_w / (n as f32);
        let bar_w = (slot_w * 0.66).clamp(6.0, 42.0);

        let ideal_y = (h - pad) - (ideal / max_v) * (h - 2.0 * pad);
        let _ = writeln!(
            out,
            r#"<line x1="{pad}" y1="{ideal_y:.1}" x2="{:.1}" y2="{ideal_y:.1}" stroke="#8a8a8a" stroke-width="1" stroke-dasharray="4,4"/>"#,
            w - pad
        );

        for (i, &pct) in loads_pct.iter().enumerate() {
            let bh = ((pct / max_v).clamp(0.0, 1.0) * (h - 2.0 * pad)).max(2.0);
            let x = pad + (i as f32) * slot_w + (slot_w - bar_w) * 0.5;
            let y = (h - pad) - bh;
            let color = if pct < ideal * 0.25 {
                "#ef4444"
            } else if pct > ideal * 2.0 {
                "#eab308"
            } else {
                "#f4f4f4"
            };
            let _ = writeln!(
                out,
                r#"<rect x="{x:.1}" y="{y:.1}" width="{bar_w:.1}" height="{bh:.1}" rx="3" fill="{color}"/>"#
            );
        }
    }

    out.push_str("</svg>");
    svg::Handle::from_memory(out.into_bytes())
}

/// Renders a visual stack diagram of the configured Transformer blocks.
pub fn arch_blueprint_svg(cfg: &TransformerConfig) -> svg::Handle {
    let (w, h) = (250.0f32, 132.0f32);
    let mut out = svg_header(w, h);
    let shown = cfg.n_layers.clamp(1, 8);
    let total_bars = shown + 2; // embed + layers + head
    let gap = 3.0f32;
    let pad = 8.0f32;
    let bar_h = ((h - 2.0 * pad - gap * (total_bars as f32 - 1.0)) / total_bars as f32).max(6.0);

    // Top bar: LM Head
    let head_fill = if cfg.tie_embeddings { "#262626" } else { "#363636" };
    let _ = writeln!(
        out,
        r#"<rect x="{pad}" y="{pad}" width="{:.1}" height="{bar_h:.1}" rx="3" fill="{head_fill}" stroke="#5c5c5c" stroke-width="1"/>"#,
        w - 2.0 * pad
    );

    // Middle bars: Transformer layers (split into Attention left + Dense/MoE right)
    for idx in 0..shown {
        let y = pad + (idx + 1) as f32 * (bar_h + gap);
        let half_w = (w - 2.0 * pad - 4.0) * 0.48;
        let right_x = pad + half_w + 4.0;
        let right_w = (w - pad) - right_x;

        let _ = writeln!(
            out,
            r#"<rect x="{pad}" y="{y:.1}" width="{half_w:.1}" height="{bar_h:.1}" rx="3" fill="#1f1f1f" stroke="#8a8a8a" stroke-width="1"/>"#
        );
        match cfg.routing {
            Routing::Dense => {
                let _ = writeln!(
                    out,
                    r#"<rect x="{right_x:.1}" y="{y:.1}" width="{right_w:.1}" height="{bar_h:.1}" rx="3" fill="#2a2a2a" stroke="#d4d4d4" stroke-width="1"/>"#
                );
            }
            Routing::MoE => {
                let segs = cfg.moe.n_experts.clamp(2, 8);
                let seg_w = (right_w - (segs as f32 - 1.0) * 2.0) / segs as f32;
                for e in 0..segs {
                    let sx = right_x + e as f32 * (seg_w + 2.0);
                    let active = e < cfg.moe.top_k;
                    let fill = if active { "#f4f4f4" } else { "#1a1a1a" };
                    let _ = writeln!(
                        out,
                        r#"<rect x="{sx:.1}" y="{y:.1}" width="{seg_w:.1}" height="{bar_h:.1}" rx="2" fill="{fill}" stroke="#5c5c5c" stroke-width="0.8"/>"#
                    );
                }
            }
        }
    }

    // Bottom bar: Token + Positional Embeddings
    let bot_y = pad + (shown + 1) as f32 * (bar_h + gap);
    let _ = writeln!(
        out,
        r#"<rect x="{pad}" y="{bot_y:.1}" width="{:.1}" height="{bar_h:.1}" rx="3" fill="#262626" stroke="#5c5c5c" stroke-width="1"/>"#,
        w - 2.0 * pad
    );

    out.push_str("</svg>");
    svg::Handle::from_memory(out.into_bytes())
}

fn svg_header(w: f32, h: f32) -> String {
    let mut s = String::with_capacity(2048);
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0} {h:.0}" width="{w:.0}" height="{h:.0}">"#
    );
    let _ = writeln!(
        s,
        r#"<rect x="0.5" y="0.5" width="{:.1}" height="{:.1}" rx="10" fill="#0d0d0d" stroke="#2c2c2c" stroke-width="1"/>"#,
        w - 1.0,
        h - 1.0
    );
    s
}

fn draw_grid(out: &mut String, w: f32, h: f32, pad: f32, rows: usize) {
    for i in 1..rows {
        let y = pad + (i as f32 / rows as f32) * (h - 2.0 * pad);
        let _ = writeln!(
            out,
            r#"<line x1="{pad}" y1="{y:.1}" x2="{:.1}" y2="{y:.1}" stroke="#1f1f1f" stroke-width="1"/>"#,
            w - pad
        );
    }
}
