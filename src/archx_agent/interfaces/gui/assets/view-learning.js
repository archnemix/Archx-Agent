/* learning view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ----------------------------------------------------------------- learning
  async function loadLearningGoals() {
    const list = shared.clear(document.getElementById("learning-goals"));
    const data = await shared.api("GET", "/api/learning?limit=30");
    if (!data.goals.length) {
      list.append(shared.el("li", { class: "list-empty", text: "no goals yet – create one below" }));
      return;
    }
    for (const goal of data.goals) {
      const stats = goal.stats;
      list.append(shared.el("li", {
        class: "list-item" + (goal.id === shared.state.learningId ? " active" : ""),
        onclick: () => openLearning(goal.id),
      }, [
        shared.el("span", { class: "t", text: goal.title }),
        shared.el("span", {
          class: "s",
          text: goal.status + " · " + stats.items + " item(s) · " + stats.due + " due · "
            + (stats.accuracy === null ? "no attempts" : Math.round(stats.accuracy * 100) + "% correct"),
        }),
      ]));
    }
  }

  function learningAnswerForm(goalId, item) {
    const answer = shared.el("textarea", { rows: "3", placeholder: "your answer" });
    const rating = shared.el("select", { class: "sel" }, [
      shared.el("option", { value: "" }, ["self-rating (needed when there is nothing to compare against)"]),
      shared.el("option", { value: "1" }, ["1 – no idea"]),
      shared.el("option", { value: "2" }, ["2 – shaky"]),
      shared.el("option", { value: "3" }, ["3 – mostly right"]),
      shared.el("option", { value: "4" }, ["4 – confident"]),
      shared.el("option", { value: "5" }, ["5 – could teach it"]),
    ]);
    const feedback = shared.el("div", { class: "warnings" });
    const form = shared.el("form", { class: "answer-form" }, [
      shared.el("label", { class: "field" }, [shared.el("span", { text: "Answer" }), answer]),
      shared.el("label", { class: "field" }, [shared.el("span", { text: "How did it go?" }), rating]),
      shared.el("div", { class: "row between" }, [
        shared.el("span", { class: "hint", text: item.graded_by_hint || "graded against the expected answer, or by your rating" }),
        shared.el("button", { class: "btn primary", type: "submit" }, ["Answer"]),
      ]),
      feedback,
    ]);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      shared.clear(feedback);
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        const result = await shared.api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/answer", {
          item_id: item.id,
          answer: answer.value,
          self_rating: rating.value || null,
        });
        const grade = result.grade;
        feedback.append(shared.el("div", { class: "feedback" }, [
          shared.el("span", { class: grade.correct ? "ok" : "no", text: (grade.correct ? "correct" : "not yet") + " · graded by " + grade.graded_by }),
          shared.el("span", { class: "why", text: grade.feedback }),
          shared.el("span", { class: "why", text: "next review " + shared.stamp(result.schedule.due_at) + " · " + result.schedule.why }),
          result.explanation ? shared.el("span", { class: "why", text: result.explanation }) : null,
        ]));
        await openLearning(goalId);
        await loadLearningGoals();
      } catch (error) {
        shared.report(feedback, error);
      } finally {
        button.disabled = false;
      }
    });
    return form;
  }

  function learningItemForm(goalId) {
    const note = shared.el("span", { class: "hint" });
    const prompt = shared.el("input", { type: "text", placeholder: "Which journal mode lets readers keep reading?" });
    const expected = shared.el("input", { type: "text", placeholder: "answer Archx can check (leave blank to self-grade)" });
    const hints = shared.el("textarea", { rows: "3", placeholder: "one hint per line, easiest first" });
    const form = shared.el("form", { class: "card" }, [
      shared.el("div", { class: "card-head" }, [shared.el("h3", { text: "Add an item" }), shared.el("p", { class: "hint", text: "The ladder is revealed one rung at a time, and never before an attempt." })]),
      shared.el("label", { class: "field" }, [shared.el("span", { text: "Prompt" }), prompt]),
      shared.el("label", { class: "field" }, [shared.el("span", { text: "Expected answer" }), expected]),
      shared.el("label", { class: "field" }, [shared.el("span", { text: "Hint ladder" }), hints]),
      shared.el("div", { class: "row between" }, [
        shared.el("button", { class: "btn primary", type: "submit" }, ["Add item"]),
        note,
      ]),
    ]);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      shared.clear(note);
      try {
        const item = await shared.api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/items", {
          prompt: prompt.value,
          expected: expected.value,
          hints: hints.value,
        });
        note.textContent = "added " + shared.shortId(item.id);
        await openLearning(goalId);
        await loadLearningGoals();
      } catch (error) {
        shared.report(note, error);
      } finally {
        button.disabled = false;
      }
    });
    return form;
  }

  async function openLearning(goalId) {
    shared.state.learningId = goalId;
    await loadLearningGoals();
    const panel = shared.clear(document.getElementById("learning-detail"));
    const data = await shared.api("GET", "/api/learning/goals/" + encodeURIComponent(goalId));
    const goal = data.goal;
    const stats = data.stats;

    panel.append(shared.el("div", { class: "goal-head" }, [
      shared.el("div", {}, [
        shared.el("h2", { text: goal.title }),
        shared.el("div", { class: "goal-meta" }, [
          shared.statusBadge(goal.status),
          shared.el("span", { text: "level " + goal.level }),
          shared.el("span", { text: stats.items + " item(s)" }),
          shared.el("span", { text: stats.due + " due" }),
          shared.el("span", { text: stats.attempts + " attempt(s)" }),
          shared.el("span", { text: stats.accuracy === null ? "nothing graded yet" : Math.round(stats.accuracy * 100) + "% correct" }),
        ]),
      ]),
      shared.el("div", { class: "row" }, [
        shared.el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => shared.api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/plan", { use_model: false })
            .then((result) => {
              shared.toast("Planned", result.items.length + " item(s) by " + result.planned_by, "ok");
              return openLearning(goalId);
            })
            .then(loadLearningGoals)
            .catch((error) => shared.toast("Could not plan items", error.message, "err")),
        }, [shared.svgIcon("plus"), "propose items"]),
        shared.el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => shared.api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/review", {})
            .then(() => openLearning(goalId))
            .catch((error) => shared.toast("Could not start a review", error.message, "err")),
        }, [shared.svgIcon("play"), "start review"]),
      ]),
    ]));

    if (goal.objective) panel.append(shared.el("p", { class: "small dim", text: goal.objective }));
    if ((goal.success_criteria || []).length) {
      panel.append(shared.el("ul", { class: "criteria" }, goal.success_criteria.map((line) => shared.el("li", { text: line }))));
    }

    const next = data.next || {};
    const nextCard = shared.el("div", { class: "next-card" });
    if (next.nothing_to_study) {
      nextCard.append(shared.el("p", { class: "why", text: next.message || "nothing to study right now" }));
    } else {
      const item = next.item;
      const ladder = shared.el("div", { class: "ladder" });
      const hintBox = shared.el("div", { class: "warnings" });
      nextCard.append(shared.el("p", { class: "why", text: next.why + (item.hint_count ? " · " + item.hint_count + " hint(s)" : "") }));
      nextCard.append(shared.el("p", { class: "question", text: item.prompt }));
      if (item.hint_count) {
        nextCard.append(shared.el("div", { class: "row" }, [
          shared.el("button", {
            class: "btn tiny",
            type: "button",
            onclick: async (event) => {
              const button = event.currentTarget;
              button.disabled = true;
              try {
                const result = await shared.api("POST", "/api/learning/items/" + encodeURIComponent(item.id) + "/hint", { level: (item.revealed || 0) + 1 });
                item.revealed = result.level;
                ladder.append(shared.el("div", { class: "rung" }, [
                  shared.el("span", { class: "lvl", text: "hint " + result.level + "/" + result.total }),
                  shared.el("span", { text: result.hint }),
                ]));
                if (result.level >= result.total) button.disabled = true;
              } catch (error) {
                shared.report(hintBox, error);
              } finally {
                button.disabled = false;
              }
            },
          }, ["Reveal a hint"]),
          shared.el("span", { class: "hint", text: "one level at a time" }),
        ]));
      }
      nextCard.append(ladder, hintBox, learningAnswerForm(goalId, item));
    }
    panel.append(nextCard);

    panel.append(shared.el("div", { class: "section-head" }, [
      shared.el("div", {}, [shared.el("h2", { text: "Items and schedule" }), shared.el("p", { text: "the arithmetic this goal is on" })]),
    ]));
    panel.append(shared.table(
      ["item", "status", "due", "streak", "interval", "next review", "prompt"],
      data.items.map((item) => [
        shared.shortId(item.id), shared.statusBadge(item.status), item.due ? "yes" : "no", String(item.streak),
        item.interval_days + "d", shared.stamp(item.due_at), item.prompt,
      ]),
      "no items yet – propose some, or add one below",
    ));

    if ((data.sessions || []).length) {
      panel.append(shared.el("div", { class: "section-head" }, [
        shared.el("div", {}, [shared.el("h2", { text: "Sessions" })]),
      ]));
      panel.append(shared.table(["session", "mode", "status", "answered", "correct", "started"], data.sessions.map((session) => [
        shared.shortId(session.id), session.mode, shared.statusBadge(session.status), String(session.items_attempted),
        String(session.items_correct), shared.stamp(session.started_at),
      ])));
    }

    panel.append(learningItemForm(goalId));
  }

  shared.loaders.learning = async () => {
    await loadLearningGoals();
    if (shared.state.learningId) await openLearning(shared.state.learningId);
  };

  document.getElementById("learning-refresh").addEventListener("click", () => {
    shared.loaders.learning().catch((error) => shared.report(document.getElementById("learning-detail"), error));
  });

  document.getElementById("learning-goal-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("learning-goal-status");
    status.textContent = "";
    const criteria = document.getElementById("learning-criteria").value.trim();
    try {
      const goal = await shared.api("POST", "/api/learning/goals", {
        title: document.getElementById("learning-title").value,
        criteria: criteria ? [criteria] : [],
      });
      document.getElementById("learning-title").value = "";
      document.getElementById("learning-criteria").value = "";
      await openLearning(goal.id);
    } catch (error) {
      shared.report(document.getElementById("learning-detail"), error);
    }
  });

});
