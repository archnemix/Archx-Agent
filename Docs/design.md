<!-- Purpose: Defines the AI app-launcher visual system and cross-platform review criteria. -->
# Archx AI Lab — design system

## Product identity

**Archx AI Lab** is the Archnemix AI/ML launcher; **Archx Agent** is its future six-mode chat-and-agent app. Model Training and Fine-tuning remain separate future destinations. Model observation is hidden from the current launcher at the user's request, not declared cancelled forever. Unbuilt areas must say *Coming later* or *In development* and never simulate working controls.

Use the broad desktop-launcher pattern—persistent navigation, a featured destination and an app shelf—without copying Epic or LDPlayer branding, art or UI. The user's selected-menu reference is a black pill with a soft silver-grey lower glow; this is a visual direction, not a request to paste the image into the app.

## Visual system

- **Canvas:** `#080808` black, `#0D0D0D` rail, restrained grey surfaces and hairline borders; near-white `#F4F4F4` type with neutral grey secondary text. No neon, saturated accents or dashboard KPI cards.
- **Active menu:** a rounded dark-to-silver-grey *native* gradient, thin light-grey rim and subtle bottom shadow. It should evoke smoked glass rather than a flat selected rectangle. No continuous blur or animation; hover is distinct, and only available pages are clickable.
- **Type:** bundled OFL-licensed Manrope. Use uncluttered hierarchy and comfortable 13–17px body labels; avoid marketing filler and tiny navigation text.
- **App identity:** the current Agent hero sculpture in `assets/agent-cover.png` and cropped `assets/agent-tile.jpg` are temporary until the user supplies and approves an animated Agent asset. The other two apps use restrained typography instead of 3D objects: Training conveys building from data; Fine-tuning conveys adapting an existing model. Each text card cycles a subtle stage highlight **only while hovered** and stops on exit, without showing fake live progress or enabling the unfinished app. Model Monitor is not on the current launcher. App names and availability remain visible at 1280 × 800.
- **Structure:** slim left brand/browse rail, clear main heading, one featured Agent surface, then a shelf of independent AI apps with a title, purpose label and status. Library and apps remain inert until implemented; About is the second working destination.

## Cross-platform review

- Build and run on Windows, Linux and macOS after each GUI step. Capture **Discover and About** to inspect both selected-menu states, image decoding, typography, cropping and contrast. Actual first-run macOS capture was limited to 1024 × 642 despite requesting 1280 × 800; lower content must remain scrollable. Target consistent app content, not byte-identical OS chrome.
- Windows release builds use PE GUI subsystem 2 and must not open a Command Prompt. CI asserts the PE subsystem and runs the app in screenshot mode; the user still needs to confirm the normal Windows launch.
- Retain only current and two preceding version results; Windows downloads live in the repository at the user's request. Monitor size as art/binaries change.

## Deferred

Training/monitoring tools, library search, accounts, live agents and additional art belong to their own approved steps. No mock action is presented as functional.

## Current brand/3D revision request

Use the user-supplied Archnemix mark in the sidebar and native window/taskbar icon, with a near-black background and faithful proportions. Remove `LOCAL PREVIEW` and `PREVIEW 01` labels; do not label unbuilt apps operational. A Windows CompanyName resource is not a publisher signature. Earlier, the user considered 3D rotating artwork for every tile. **Superseded:** only Archx Agent should eventually use a genuine animated Agent image/model once its asset is provided and approved; Training and Fine-tuning use text-based hover motion, not 3D. Keep a reduced-motion/fallback path for the later Agent animation, bound all visuals within cards, and review the actual motion on all three OSes. This Agent animation is not yet implemented.
