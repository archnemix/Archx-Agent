//! Purpose: Owns the launcher↔app transition (a short fade/slide) so the change of screen never cuts abruptly.
//!
//! One `Transition` per view direction. A fade-in is applied to the arriving
//! screen only: two stacked layers would need a fade-out as well, and letting a
//! half-transparent launcher sit on top of the app would also steal clicks.
//! The transition is time-based, driven by the app's own `Ticker` subscription
//! (~30 frames per second) so it lasts the same wall-clock time on every OS and
//! in the deterministic screenshot path (`ARCHX_SNAPSHOT` fixes it complete).

use crate::app::Page;

/// How long one transition lasts.
pub const DURATION_MS: u64 = 220;
/// Frame interval for the ticker while something is moving.
pub const FRAME_MS: u64 = 33;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    /// Launcher → app.
    Enter,
    /// App → launcher.
    Leave,
    /// Agent Chat ↔ Agent Settings (same app, different surface).
    Within,
}

impl Direction {
    /// Distance in pixels the arriving screen slides from.
    pub fn slide(self) -> f32 {
        match self {
            Self::Enter => 14.0,
            Self::Leave => 10.0,
            Self::Within => 6.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transition {
    pub direction: Direction,
    /// Milliseconds since the transition started.
    pub elapsed_ms: u64,
}

impl Transition {
    /// Starts a transition, choosing the direction from the two pages.
    pub fn between(from: Page, to: Page) -> Self {
        let app_pages = |page: Page| page.is_agent_surface();
        let direction = match (app_pages(from), app_pages(to)) {
            (false, true) => Direction::Enter,
            (true, false) => Direction::Leave,
            _ => Direction::Within,
        };
        Self { direction, elapsed_ms: 0 }
    }

    pub fn is_complete(self) -> bool {
        self.elapsed_ms >= DURATION_MS
    }

    /// Linear progress in 0..=1. Eased as an ease-out cubic so the arrival
    /// settles rather than stopping dead.
    pub fn progress(self) -> f32 {
        let linear = (self.elapsed_ms.min(DURATION_MS) as f32) / DURATION_MS as f32;
        let inverse = 1.0 - linear;
        1.0 - inverse * inverse * inverse
    }

    /// Opacity for the arriving screen (never fully invisible: a screen that
    /// starts at 0 can flash if the first frame is late).
    pub fn opacity(self) -> f32 {
        0.35 + 0.65 * self.progress()
    }

    /// Vertical offset for the arriving screen, in pixels (top padding).
    pub fn offset(self) -> f32 {
        self.direction.slide() * (1.0 - self.progress())
    }

    pub fn advance(mut self, elapsed_ms: u64) -> Self {
        self.elapsed_ms = self.elapsed_ms.saturating_add(elapsed_ms);
        self
    }
}

/// Whether the ticker subscription should run.
pub fn animating(transition: Option<Transition>) -> bool {
    transition.is_some_and(|transition| !transition.is_complete())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn directions_follow_the_page_kind() {
        assert_eq!(Transition::between(Page::Home, Page::Agent).direction, Direction::Enter);
        assert_eq!(Transition::between(Page::Agent, Page::Home).direction, Direction::Leave);
        assert_eq!(Transition::between(Page::Agent, Page::AgentSettings).direction, Direction::Within);
        assert_eq!(Transition::between(Page::Home, Page::About).direction, Direction::Within);
        assert!(Direction::Enter.slide() > Direction::Within.slide());
    }

    #[test]
    fn progress_is_monotonic_and_lands_exactly_complete() {
        let mut transition = Transition { direction: Direction::Enter, elapsed_ms: 0 };
        let mut last = transition.progress();
        assert!(last.abs() < 1e-6);
        assert_eq!(transition.opacity(), 0.35);
        assert_eq!(transition.offset(), Direction::Enter.slide());
        for _ in 0..12 {
            transition = transition.advance(FRAME_MS);
            let progress = transition.progress();
            assert!(progress >= last, "progress must not go backwards");
            last = progress;
        }
        transition = transition.advance(DURATION_MS);
        assert!(transition.is_complete());
        assert_eq!(transition.progress(), 1.0);
        assert_eq!(transition.opacity(), 1.0);
        assert_eq!(transition.offset(), 0.0);
        assert!(!animating(Some(transition)));
        assert!(!animating(None));
        assert!(animating(Some(Transition { direction: Direction::Leave, elapsed_ms: 10 })));
    }

    #[test]
    fn opacity_never_starts_from_zero_so_arrival_cannot_flash() {
        let start = Transition { direction: Direction::Enter, elapsed_ms: 0 };
        assert!(start.opacity() >= 0.3);
        assert!(start.opacity() < 0.5);
        let mid = Transition { direction: Direction::Enter, elapsed_ms: DURATION_MS / 2 };
        assert!(mid.opacity() > start.opacity() && mid.opacity() < 1.0);
    }
}
