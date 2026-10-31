# Feature-by-feature plan

The supplied reference is the only active foundation. Retire the old milestone,
subsystem and checklist-completion approach. Keep the original requirements, not
past completion claims or a second implementation.

The complete feature list, acceptance conditions and honest current position are
in [Complete features and acceptance requirements](docs/FEATURE_REQUIREMENTS.md).

## Current feature: Simple Mode

Finish the entire agreed chat journey, including provider/key/model setup, actual
model replies, thinking when supplied, conversation controls, persistence, errors
and a clean desktop/mobile interface. Edit, regeneration and branch flows still
need full verification. The user tests with their own key in the live preview.
Do not call this complete before their acceptance.

## Rule for every feature

1. Agree its complete behaviour and required supported integrations.
2. Implement that behaviour, including the necessary settings and failure paths.
3. Run only the checks needed to cover distinct behaviours and risks; reuse useful
   existing checks instead of adding duplicate tests or chasing test totals.
4. Run the actual application on the preview port for the user's personal test.
5. Fix their findings within this feature. Move to the next feature only after
   explicit user acceptance. Do not open parallel partial modes.

Next feature after acceptance: Agent Mode. No Agent implementation is claimed today.
