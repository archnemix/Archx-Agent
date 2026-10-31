/* access view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- access
  shared.loaders.access = async () => {
    const approvals = await shared.api("GET", "/api/approvals?status=pending");
    const list = shared.clear(document.getElementById("approvals-list"));
    if (!approvals.length) {
      list.append(shared.el("p", { class: "muted-box", text: "no pending approvals" }));
    } else {
      list.append(shared.table(["id", "capability", "subject", "scope", "why", "decide"], approvals.map((approval) => [
        shared.shortId(approval.id), approval.capability, approval.subject, approval.scope, approval.reason,
        shared.el("div", { class: "row" }, [
          shared.el("button", {
            class: "btn tiny primary",
            type: "button",
            onclick: async () => {
              try {
                await shared.api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/approve", {});
                shared.toast("Approved", approval.capability + " for " + approval.subject, "ok");
                await shared.loaders.access();
                shared.invalidateStatus();
              } catch (error) { shared.toast("Could not approve", error.message, "err"); }
            },
          }, ["approve"]),
          shared.el("button", {
            class: "btn tiny danger",
            type: "button",
            onclick: async () => {
              const sure = await shared.ask({
                title: "Deny this request?",
                text: approval.capability + " for " + approval.subject + " will not be granted. The request stays in the record as denied.",
                okLabel: "Deny",
              });
              if (!sure) return;
              try {
                await shared.api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/deny", {});
                shared.toast("Denied", approval.capability + " was not granted", "warn");
                await shared.loaders.access();
                shared.invalidateStatus();
              } catch (error) { shared.toast("Could not deny", error.message, "err"); }
            },
          }, ["deny"]),
        ]),
      ])));
    }

    const permissions = await shared.api("GET", "/api/permissions?active_only=1");
    const grants = shared.clear(document.getElementById("grants-list"));
    if (!permissions.grants.length) {
      grants.append(shared.el("p", { class: "muted-box", text: "no active grants – nothing can touch your files, run a program or fetch the web" }));
    } else {
      grants.append(shared.table(["id", "capability", "subject", "scope", "expires", ""], permissions.grants.map((grant) => [
        shared.shortId(grant.id), grant.capability, grant.subject, grant.scope, grant.expires_at ? shared.stamp(grant.expires_at) : "no expiry",
        shared.el("button", {
          class: "btn tiny danger",
          type: "button",
          onclick: async () => {
            const sure = await shared.ask({
              title: "Revoke this grant?",
              text: grant.capability + " for " + grant.subject + " stops working immediately. Anything mid-flight that needed it will fail and say so.",
              okLabel: "Revoke",
            });
            if (!sure) return;
            try {
              await shared.api("POST", "/api/permissions/" + encodeURIComponent(grant.id) + "/revoke", {});
              shared.toast("Revoked", grant.capability + " for " + grant.subject, "ok");
              await shared.loaders.access();
              shared.invalidateStatus();
            } catch (error) { shared.toast("Could not revoke", error.message, "err"); }
          },
        }, ["revoke"]),
      ])));
    }

    const caps = shared.clear(document.getElementById("capabilities-list"));
    caps.append(shared.table(["capability", "risk", "effect", "what it allows"], permissions.capabilities.map((cap) => [
      cap.name, shared.badge(cap.risk, cap.risk === "high" ? "bad" : cap.risk === "medium" ? "warn" : ""), cap.effect, cap.description,
    ])));
  };

  document.getElementById("access-refresh").addEventListener("click", () => {
    shared.loaders.access().catch((error) => shared.report(document.getElementById("grants-list"), error));
  });

});
