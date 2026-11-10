<!-- Purpose: Defines the visual language and interaction rules for the Archx AI Lab desktop interface. -->
# Archx AI Lab — design system

## Product hierarchy

- **Archx AI Lab** is the AI/ML launcher and future workspace; **Archx Agent** is its chat-and-agent destination. Archx abbreviates Archnemix.
- The home screen is the entrance to a growing ecosystem, not a chat window. Show Agent, model training, fine-tuning, and model observation as distinct destinations. In the first build, unfinished destinations must be visibly marked *Coming later*, not clickable mock functions.
- Inspiration is the discoverability and navigation structure of desktop launchers (Steam/Epic/LDPlayer), not their branding or artwork. Iced's official gallery and styling examples informed the native-widget layout and styling approach; no borrowed assets.

## Visual system — first home screen

- Canvas: near-black charcoal `#101113`; surface `#191A1D`; elevated surface `#222428`; selected navigation: translucent-looking slate `#303337`; hairline border `#34363A`.
- Text: near-white `#F3F3F0`, secondary `#B0B2B5`, quiet `#797D82`. Accent: restrained warm silver `#D2D4D0` for focus and key calls to action. No neon or saturated gradients.
- Typography: locally bundled OFL-licensed **Manrope** so letterforms are consistent across OSes; OS fallback for unsupported glyphs. Large, calm headlines; readable 14–16px body. Preserve the original font license in `assets/fonts/OFL.txt`.
- Layout: compact left rail for identity and navigation; spacious main canvas with a clear hero, one prominent Agent entry, and a small, legible grid of future AI/ML workspaces. Use rhythm (8/16/24/32px), restrained rounding, quiet borders, and generous whitespace.
- Selected menu state uses an opaque gray overlay with a soft border to *suggest* smoked glass. Avoid real blur, translucency, or perpetual animation until supported and measured across all targets.
- Status labels and contrast must communicate unavailable actions without relying on color alone. Avoid tiny text and truncated labels at normal desktop widths.

## Cross-platform review

- First-class targets: Windows, Linux, macOS. Request the same window/content dimensions on each OS after every GUI milestone; record actual screenshot dimensions and inspect alignment, clipping, font fallback, contrast, and selected-state rendering. The first macOS runner limited the captured window to 1024 × 642 despite the requested 1280 × 800, while Windows/Linux captured 1280 × 800. Compare content at equivalent viewports where possible; do not claim byte-identical pixels or a full-page inspection from a shorter capture.
- Validate a compact window as well as the default size, and keep long content scrollable. Prefer responsiveness to a hard-coded pixel layout.
- Keep screenshots and concise test output organized by version, retaining the current and two preceding versions. Provide a downloadable Windows build at each GUI step; the user chose storing the build in the repository. Avoid retaining unlimited historical binaries.

## Deferred

No final illustrations, icon pack, animated backgrounds, blur effects, training UI, or model dashboards have been approved. Add them only when their owning functionality is built.
