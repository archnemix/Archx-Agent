//! Purpose: Describes and renders distinct, unavailable AI apps in the launcher shelf.
use std::sync::LazyLock;

use iced::widget::{column, image, space, text};
use iced::{ContentFit, Element, Fill, FillPortion};

use crate::app::Message;
use crate::style;

#[derive(Clone, Copy)]
pub enum Art {
    Agent,
    Training,
    Tuning,
    Monitor,
}

pub struct AppTile {
    pub name: &'static str,
    pub category: &'static str,
    pub art: Art,
}

pub const APPS: [AppTile; 4] = [
    AppTile { name: "Archx Agent", category: "CHAT & AGENTS", art: Art::Agent },
    AppTile { name: "Model Training", category: "BUILD MODELS", art: Art::Training },
    AppTile { name: "Fine-tuning", category: "REFINE MODELS", art: Art::Tuning },
    AppTile { name: "Model Monitor", category: "OBSERVE MODELS", art: Art::Monitor },
];

static AGENT: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/agent-cover.png").to_vec())
});
static TRAINING: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/model-training.jpg").to_vec())
});
static TUNING: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/fine-tuning.jpg").to_vec())
});
static MONITOR: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/model-monitor.jpg").to_vec())
});

fn art(art: Art) -> image::Handle {
    match art {
        Art::Agent => AGENT.clone(),
        Art::Training => TRAINING.clone(),
        Art::Tuning => TUNING.clone(),
        Art::Monitor => MONITOR.clone(),
    }
}

pub fn view(tile: &'static AppTile) -> Element<'static, Message> {
    column![
        image(art(tile.art))
            .width(Fill)
            .height(140)
            .content_fit(ContentFit::Cover)
            .border_radius(12),
        space().height(14),
        text(tile.category).size(10).color(style::DIM),
        space().height(5),
        text(tile.name).size(17).color(style::WHITE),
        space().height(5),
        text("COMING LATER").size(11).color(style::GREY)
    ]
    .width(FillPortion(1))
    .into()
}

#[cfg(test)]
mod tests {
    use super::APPS;
    use std::collections::HashSet;

    #[test]
    fn app_tiles_have_unique_names() {
        let names: HashSet<_> = APPS.iter().map(|app| app.name).collect();
        assert_eq!(names.len(), APPS.len());
    }
}
