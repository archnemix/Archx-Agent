<!-- Purpose: Defines the AI app-launcher visual system and cross-platform review criteria. -->
# Archx AI Lab — design system

## Product identity

**Archx AI Lab** is the Archnemix AI/ML launcher; **Archx Agent** is its future six-mode chat-and-agent app. Model Training and Fine-tuning remain separate future destinations. Model observation is hidden from the current launcher at the user's request, not declared cancelled forever. Unbuilt areas must say *Coming later* or *In development* and never simulate working controls.

Use the broad desktop-launcher pattern—persistent navigation, a featured destination and an app shelf—without copying Epic or LDPlayer branding, art or UI. The user's selected-menu reference is a black pill with a soft silver-grey lower glow; this is a visual direction, not a request to paste the image into the app.

## Visual system

- **Canvas:** `#080808` black, `#0D0D0D` rail, restrained grey surfaces and hairline borders; near-white `#F4F4F4` type with neutral grey secondary text. No neon, saturated accents or dashboard KPI cards.
- **Active menu:** a rounded dark-to-silver-grey *native* gradient, thin light-grey rim and subtle bottom shadow. It should evoke smoked glass rather than a flat selected rectangle. No continuous blur or animation; hover is distinct, and only available pages are clickable.
- **Type:** bundled OFL-licensed Manrope. Use uncluttered hierarchy and comfortable 13–17px body labels; avoid marketing filler and tiny navigation text.
- **App identity:** the user rejected the Agent sculpture cover. The Agent hero and shelf panel use distinct **kinetic typography** (`ARCHX / AGENT`, a cycle through all six mode names, and six small phase markers) rather than a plain caption or pre-rendered image. It advances while Home is visible, without claiming the modes work. Training and Fine-tuning retain quieter text-only panels: Training conveys building from data; Fine-tuning conveys adapting an existing model. Their stage emphasis advances **only while hovered** and stops on exit. Model Monitor is not on the current launcher. All unfinished apps remain visibly unavailable.
- **Structure:** slim left brand/browse rail, clear main heading, one featured Agent surface, then a shelf of independent AI apps with a title, purpose label and status. Library and apps remain inert until implemented; About is the second working destination.

## Cross-platform review

- Build and run on Windows, Linux and macOS after each GUI step. Capture **Discover and About** to inspect both selected-menu states, image decoding, typography, cropping and contrast. Actual first-run macOS capture was limited to 1024 × 642 despite requesting 1280 × 800; lower content must remain scrollable. Target consistent app content, not byte-identical OS chrome.
- Windows release builds use PE GUI subsystem 2 and must not open a Command Prompt. CI asserts the PE subsystem and runs the app in screenshot mode; the user still needs to confirm the normal Windows launch.
- Retain only current and two preceding version results; Windows downloads live in the repository at the user's request. Monitor size as art/binaries change.

## Deferred

Training/monitoring tools, library search, accounts, live agents and additional art belong to their own approved steps. No mock action is presented as functional.

## Current brand/3D revision request

Use the user-supplied Archnemix mark in the sidebar and native window/taskbar icon. The sidebar mark is a **smaller transparent crop** directly on the rail, without its own black square; the OS icon can retain a black backing for legibility. Remove `LOCAL PREVIEW` and `PREVIEW 01` labels; do not label unbuilt apps operational. A Windows CompanyName resource is not a publisher signature. Earlier, the user considered 3D rotating artwork for every tile and later Agent-only 3D. **Both are superseded by the latest request:** Agent uses animated text, not the rejected sculpture or an unapproved 3D model; Training and Fine-tuning use smaller text-based hover motion. Keep visuals bounded and review distinct frames on Windows, Linux and macOS. Future reduced-motion and resource settings remain a separate design decision, not an implemented feature.
