<!-- Purpose: Tracks user-requested product scope changes and their roadmap effects. -->
# Requested changes

## 2026-11-09 — General task agent and delivery order

- **Request:** Add a general task agent alongside simple chat, coding, learning, research, and play. Begin with the home screen, then the chat interface and mode navigation, then implement each mode completely in sequence.
- **Roadmap effect:** Added the general task agent as a distinct milestone after the shared agent/memory foundation; separated the home shell and chat UI from the modes' working behavior. Mode order after the foundation can be revisited with the user.
- **Delivery condition:** After each GUI step, provide a downloadable Windows build for hands-on testing, while running relevant checks on Windows, Linux, and macOS. Agree how large build downloads are distributed before Step 1.
- **Open:** Define general-task tool/memory boundaries and whether simple chat can convert to general task mode. No agent feature has been implemented yet.

## 2026-11-09 — AI Lab identity and home-screen design

- **Request:** Name the AI/ML launcher **Archx AI Lab**; reserve **Archx Agent** for the chat destination. Include future entries for model training, fine-tuning, and model observation. Use a sleek, minimal graphite/black style, professional typeface, and restrained gray glass-like menu selection. Capture/inspect the running UI on Windows, Linux, and macOS; the user chose repository-hosted Windows builds.
- **Roadmap effect:** Step 1 is the AI Lab home shell with the future areas visibly unavailable. Their actual capabilities remain later scope. Cross-platform screenshots and a Windows executable are part of the Step 1 completion gate.
- **Open:** Actual functionality and naming of future model workspaces are not yet approved; no claim of pixel-identical OS chrome or successful build before runner review.

## 2026-11-09 — Windows console fix and app-launcher redesign

- **Request:** The portable Windows GUI must not leave a Command Prompt open. Replace the generic dark dashboard look with a proper app-launcher entrance inspired by Epic/LDPlayer browsing: true black, restrained grey/white, selected smoky-grey menu state, and clearly app-based AI destinations.
- **Roadmap effect:** Reopen Step 1 for correction; do not start Step 2 until the updated Windows executable is delivered and three-OS builds, snapshots, and Windows GUI-subsystem assertion pass.
- **Design:** Updated `Docs/design.md`. The artwork is original monochrome Agent cover imagery, not copied launcher art or neon UI.

## 2026-11-09 — Reference-led active state and less generic app shelf

- **Request:** Replace the flat selected About/Discover rectangle with a sleek dark pill and soft silver-grey bottom glow like the supplied reference. Make the overall launcher more distinctive, cleaner, glassier and less generic without making it dense or flashy.
- **Roadmap effect:** Step 1 stays open for a new three-OS UI review and Windows build; do not start chat. Inspect selected states on both available pages.
- **Design:** Use an inexpensive native Iced gradient, thin rim and subtle shadow; add four distinct monochrome app cover images so destinations read as separate apps. Keep them inert until built.

## 2026-11-09 — Bounded covers and current review evidence

- **Visual finding:** The reference-led run `43016569988` passed all three OS tests but its Home screenshots showed blank shelf art on Windows/macOS and art overlapping text on Linux. This was a cross-renderer layout issue, not a successful review build.
- **Change:** Normalized four app tile images to 800 × 480, added a cropped Agent tile, clipped each cover within a fixed-height container, waited five seconds before CI snapshots, and tested decoding all four bundled covers. Kept the original full-width Agent feature image.
- **Validation:** Run `43020392009` passed all three jobs (4 tests each), captured Home/About on each platform and asserted Windows GUI subsystem `2`. Reviewed the updated Home PNGs: covers and names are visible without overlap on 1280 × 800 Windows/Linux; compact macOS shows the shelf art but its names remain below the fold, reachable by scrolling. About PNGs from the immediately preceding run show the same glass selected state; the workflow produced new About PNGs for this run. Exact evidence and limitations are recorded in `Docs/Test_Results/Unreleased/Gui_Validation.md`.
- **Pending:** User hands-on review and approval of the Windows launcher. Step 2 remains blocked.
