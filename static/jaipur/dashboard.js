(() => {
  "use strict";

  const isHttp = location.protocol === "http:" || location.protocol === "https:";
  if (isHttp) {
    import("./live-view.js").then(live => initLive(live)).catch(err => {
      console.warn("Live view init failed, falling back to static mockup:", err);
      initStatic();
    });
  } else {
    initStatic();
  }

  function switchView(viewName) {
    const views = {
      overview: document.querySelector("#view-overview"),
      expenses: document.querySelector("#view-expenses"),
      receipts: document.querySelector("#view-receipts"),
      balances: document.querySelector("#view-balances"),
      fund: document.querySelector("#view-fund"),
      members: document.querySelector("#view-members"),
      "ai-guide": document.querySelector("#view-ai-guide"),
      settings: document.querySelector("#view-settings"),
    };
    for (const [key, el] of Object.entries(views)) {
      if (el) el.hidden = key !== viewName;
    }
    const navButtons = document.querySelectorAll("[data-nav]");
    for (const btn of navButtons) {
      if (btn.dataset.nav === viewName) {
        btn.setAttribute("aria-current", "page");
      } else {
        btn.removeAttribute("aria-current");
      }
    }
    const crumbDivider = document.querySelector("#crumb-view-divider");
    const crumbTitle = document.querySelector("#crumb-view-title");
    const titles = {
      overview: "Overview",
      expenses: "Expenses",
      receipts: "Receipts & Azure AI",
      balances: "Balances & Settlements",
      fund: "Trip Advance Fund",
      members: "Group Members",
      "ai-guide": "AI-900 & Architecture",
      settings: "Settings",
    };
    if (crumbDivider && crumbTitle) {
      if (viewName === "overview") {
        crumbDivider.hidden = true;
        crumbTitle.hidden = true;
      } else {
        crumbDivider.hidden = false;
        crumbTitle.hidden = false;
        crumbTitle.textContent = titles[viewName] || "Workspace";
      }
    }
    if (viewName === "ai-guide") {
      initInteractiveCalc();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function initInteractiveCalc() {
    const pizzaEl = document.querySelector("#calc-pizza");
    const thaliEl = document.querySelector("#calc-thali");
    const drinksEl = document.querySelector("#calc-drinks");
    const taxEl = document.querySelector("#calc-tax");
    const totalDisplay = document.querySelector("#calc-total-display");
    const amanDisplay = document.querySelector("#calc-aman-display");
    const simranDisplay = document.querySelector("#calc-simran-display");
    const karanDisplay = document.querySelector("#calc-karan-display");
    const checkDisplay = document.querySelector("#calc-check-display");

    if (!pizzaEl || !thaliEl || !drinksEl || !taxEl) return;

    function recalculate() {
      const pizzaPaise = Math.round((parseFloat(pizzaEl.value) || 0) * 100);
      const thaliPaise = Math.round((parseFloat(thaliEl.value) || 0) * 100);
      const drinksPaise = Math.round((parseFloat(drinksEl.value) || 0) * 100);
      const taxPaise = Math.round((parseFloat(taxEl.value) || 0) * 100);

      const pizzaAman = Math.floor(pizzaPaise / 2);
      const pizzaSimran = pizzaPaise - pizzaAman;

      const drinkPer = Math.floor(drinksPaise / 3);
      const drinkRem = drinksPaise - drinkPer * 3;
      const drinksAman = drinkPer + (drinkRem > 0 ? 1 : 0);
      const drinksSimran = drinkPer + (drinkRem > 1 ? 1 : 0);
      const drinksKaran = drinkPer;

      const amanSub = pizzaAman + drinksAman;
      const simranSub = pizzaSimran + drinksSimran;
      const karanSub = thaliPaise + drinksKaran;
      const totalItems = amanSub + simranSub + karanSub;

      let amanTax = 0;
      let simranTax = 0;
      let karanTax = 0;

      if (totalItems > 0) {
        amanTax = Math.floor((amanSub / totalItems) * taxPaise);
        simranTax = Math.floor((simranSub / totalItems) * taxPaise);
        karanTax = Math.floor((karanSub / totalItems) * taxPaise);
        const taxRem = taxPaise - (amanTax + simranTax + karanTax);
        const fracAman = ((amanSub / totalItems) * taxPaise) - amanTax;
        const fracSimran = ((simranSub / totalItems) * taxPaise) - simranTax;
        const fracKaran = ((karanSub / totalItems) * taxPaise) - karanTax;
        const rems = [
          { id: "karan", val: fracKaran },
          { id: "simran", val: fracSimran },
          { id: "aman", val: fracAman }
        ].sort((a, b) => b.val - a.val);

        for (let i = 0; i < taxRem; i++) {
          if (rems[i].id === "aman") amanTax++;
          else if (rems[i].id === "simran") simranTax++;
          else if (rems[i].id === "karan") karanTax++;
        }
      } else {
        amanTax = Math.floor(taxPaise / 3);
        simranTax = Math.floor(taxPaise / 3);
        karanTax = taxPaise - amanTax - simranTax;
      }

      const amanTotal = amanSub + amanTax;
      const simranTotal = simranSub + simranTax;
      const karanTotal = karanSub + karanTax;
      const grandTotal = totalItems + taxPaise;

      const inr = paise => "₹" + (paise / 100).toFixed(2);

      if (totalDisplay) totalDisplay.textContent = inr(grandTotal);
      if (amanDisplay) amanDisplay.textContent = inr(amanTotal);
      if (simranDisplay) simranDisplay.textContent = inr(simranTotal);
      if (karanDisplay) karanDisplay.textContent = inr(karanTotal);
      if (checkDisplay) {
        const sumShares = amanTotal + simranTotal + karanTotal;
        const diff = grandTotal - sumShares;
        checkDisplay.textContent = diff === 0 ? "✓ Exact (0 diff)" : `Mismatch: ${diff} paise`;
      }
    }

    [pizzaEl, thaliEl, drinksEl, taxEl].forEach(input => {
      input.removeEventListener("input", recalculate);
      input.addEventListener("input", recalculate);
    });
    recalculate();
  }

  function toggleNotifications(force) {
    const notifDropdown = document.querySelector("#notifications-dropdown");
    const noticeBtn = document.querySelector(".notice-button");
    if (!notifDropdown) return;
    const isHidden = force !== undefined ? !force : !notifDropdown.hidden;
    notifDropdown.hidden = isHidden;
    noticeBtn?.setAttribute("aria-expanded", String(!isHidden));
  }

  function toggleGroupDropdown(force) {
    const dropdown = document.querySelector("#group-dropdown");
    const toggle = document.querySelector("#group-toggle");
    if (!dropdown) return;
    const isHidden = force !== undefined ? !force : !dropdown.hidden;
    dropdown.hidden = isHidden;
    toggle?.setAttribute("aria-expanded", String(!isHidden));
  }

  async function initLive(live) {
    const review = document.querySelector("#receipt-review");
    const tool = document.querySelector("#dashboard-tool");
    const toolTitle = document.querySelector("#tool-title");
    const toolContent = document.querySelector("#tool-content");
    const returnFocus = new WeakMap();

    function openDialog(dialog, opener) {
      if (dialog.open) return;
      returnFocus.set(dialog, opener);
      dialog.showModal();
    }

    function openTool(title, markup, opener) {
      toolTitle.textContent = title;
      toolContent.innerHTML = markup;
      openDialog(tool, opener);
    }

    let csrfToken = "";
    let currentSession = null;
    let currentGroup = null;
    let groupData = null;
    let currentFilter = "all";
    let currentSelectedId = null;
    let availableGroups = [];

    async function api(path, method = "GET", body = null, extraHeaders = {}) {
      const options = { method, headers: { ...extraHeaders } };
      if (csrfToken && method !== "GET" && method !== "HEAD") {
        options.headers["X-CSRF-Token"] = csrfToken;
      }
      if (body !== null) {
        if (body instanceof FormData) {
          options.body = body;
        } else {
          options.headers["Content-Type"] = "application/json";
          options.body = JSON.stringify(body);
        }
      }
      const res = await fetch(path, options);
      if (!res.ok) {
        let err = `Request failed: ${res.status}`;
        try {
          const json = await res.json();
          if (json.error) err = json.error;
        } catch {}
        throw new Error(err);
      }
      return res.json();
    }

    function updateNotificationsUI(expenses) {
      const pending = (expenses || []).filter(e => e.draft_id || !e.current_revision_id);
      const badge = document.querySelector(".notif-badge");
      const subtitle = document.querySelector(".notif-subtitle");
      const notifList = document.querySelector("#notif-list");
      const noticeBtn = document.querySelector(".notice-button");

      if (noticeBtn) {
        noticeBtn.classList.toggle("has-pending", pending.length > 0);
      }
      if (badge) badge.textContent = `${pending.length} pending`;
      if (subtitle) {
        subtitle.textContent = pending.length > 0
          ? "Group dinner needs reconciliation"
          : "All group expenses are settled";
      }

      if (notifList && pending.length > 0) {
        const dinner = pending.find(e => (e.merchant || "").toLowerCase().includes("kitchen") || (e.title || "").toLowerCase().includes("dinner")) || pending[0];
        const diffPaise = Math.abs(dinner.difference_paise || 4000);
        const diffFmt = "₹" + (diffPaise / 100).toFixed(2);

        notifList.innerHTML = `
          <div class="notif-item notif-warning">
            <div class="notif-item-icon notif-amber"><svg class="icon"><use href="#i-receipt"/></svg></div>
            <div class="notif-item-content">
              <div class="notif-item-meta"><strong>Review receipt</strong><time>17 Nov</time></div>
              <p>${dinner.merchant || "Group dinner"} has a <strong>${diffFmt} difference</strong> between scanned items and bill total.</p>
              <button type="button" class="pill-button review-expense notif-btn" data-action="review" data-receipt="${dinner.id}"><svg class="icon"><use href="#i-receipt"/></svg>Review receipt</button>
            </div>
          </div>
          <div class="notif-item">
            <div class="notif-item-icon notif-blue"><svg class="icon"><use href="#i-bus"/></svg></div>
            <div class="notif-item-content">
              <div class="notif-item-meta"><strong>Transport booking</strong><time>16 Nov</time></div>
              <p>₹3,200.00 coach transfer paid from trip advance fund. Settled.</p>
            </div>
          </div>
          <div class="notif-item">
            <div class="notif-item-icon notif-green"><svg class="icon"><use href="#i-cup"/></svg></div>
            <div class="notif-item-content">
              <div class="notif-item-meta"><strong>Refreshments</strong><time>18 Nov</time></div>
              <p>₹450.00 paid by Karan. Split equally among 3 members.</p>
            </div>
          </div>
        `;
      } else if (notifList) {
        notifList.innerHTML = `
          <div class="notif-item">
            <div class="notif-item-icon notif-blue"><svg class="icon"><use href="#i-check"/></svg></div>
            <div class="notif-item-content">
              <div class="notif-item-meta"><strong>All Clear</strong><time>Today</time></div>
              <p>All scanned receipts have been reviewed and reconciled to integer paise.</p>
            </div>
          </div>
        `;
      }
    }

    function updateGroupSwitcher(groups, activeGroup) {
      const activeLabel = document.querySelector("#active-group-label");
      const crumbName = document.querySelector("#crumb-group-name");
      const dropdownList = document.querySelector("#group-dropdown-list");

      if (activeLabel) activeLabel.textContent = activeGroup?.name || "Shared workspace";
      if (crumbName) crumbName.textContent = activeGroup?.name || "Jaipur visit";

      if (dropdownList && groups && groups.length) {
        dropdownList.innerHTML = groups.map(g => {
          const isSelected = String(g.id) === String(activeGroup?.id) || g.name === activeGroup?.name;
          return `
            <button type="button" class="group-item${isSelected ? " is-selected" : ""}" data-group-select-id="${g.id}" data-group-name="${g.name}">
              <span class="${isSelected ? "group-check" : "group-item-icon"}">
                <svg class="icon"><use href="#i-${isSelected ? "check" : "members"}"/></svg>
              </span>
              <span class="group-item-title">${g.name}</span>
            </button>
          `;
        }).join("");
      }
    }

    function bindSettingsHandlers(group, members) {
      const nameInput = document.querySelector("#settings-group-name");
      const form = document.querySelector("#settings-profile-form");
      const feedback = document.querySelector("#settings-feedback");
      const exportBtn = document.querySelector("#btn-export-json");
      const printBtn = document.querySelector("#btn-print-report");
      const resetBtn = document.querySelector("#btn-reset-demo");
      const membersTbody = document.querySelector("#settings-members-body");

      if (nameInput && group) {
        nameInput.value = group.name || "";
      }

      if (membersTbody && members && members.length) {
        membersTbody.innerHTML = members.map(m => `
          <tr>
            <td>
              <div class="member-cell">
                <span class="avatar avatar-${(m.name || "").toLowerCase().startsWith("simran") ? "simran" : (m.name || "").toLowerCase().startsWith("karan") ? "karan" : "aman"}">${(m.name || "?")[0]}</span>
                <strong>${m.name}</strong>
              </div>
            </td>
            <td>${m.email || m.name.toLowerCase().replace(/\s+/g, ".") + "@thrive.demo"}</td>
            <td><span class="badge ${m.role === "organizer" ? "badge-organizer" : "badge-member"}">${m.role === "organizer" ? "Organizer" : "Member"}</span></td>
            <td><span class="status status-settled"><svg class="icon"><use href="#i-check"/></svg>Active</span></td>
          </tr>
        `).join("");
      }

      if (form) {
        form.onsubmit = async event => {
          event.preventDefault();
          const newName = nameInput.value.trim();
          if (newName) {
            try {
              await api(`/api/groups/${group.id}`, "PATCH", { name: newName });
            } catch {}
            group.name = newName;
            updateGroupSwitcher(availableGroups, group);
            if (feedback) {
              feedback.textContent = "✓ Settings saved successfully.";
              setTimeout(() => { if (feedback) feedback.textContent = ""; }, 3000);
            }
          }
        };
      }

      if (exportBtn) {
        exportBtn.onclick = () => {
          const exportData = {
            group: group,
            members: members,
            expenses: groupData?.expenses || [],
            exported_at: new Date().toISOString(),
          };
          const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportData, null, 2));
          const downloadAnchor = document.createElement("a");
          downloadAnchor.setAttribute("href", dataStr);
          downloadAnchor.setAttribute("download", `thrive-group-${group?.id || "demo"}.json`);
          document.body.appendChild(downloadAnchor);
          downloadAnchor.click();
          downloadAnchor.remove();
        };
      }

      if (printBtn) {
        printBtn.onclick = () => window.print();
      }

      if (resetBtn) {
        resetBtn.onclick = () => window.location.reload();
      }
    }

    try {
      currentSession = await api("/api/session");
      csrfToken = currentSession.csrf || "";
      const groupsRes = await api("/api/groups");
      availableGroups = groupsRes.groups || [];
      const params = new URLSearchParams(location.search);
      const requestedGroupId = params.get("group");
      if (requestedGroupId) {
        currentGroup = availableGroups.find(g => String(g.id) === requestedGroupId);
      }
      if (!currentGroup) {
        currentGroup = availableGroups.find(g => g.name === "Jaipur Industrial Visit") || availableGroups[0];
      }
      if (!currentGroup) {
        initStatic();
        return;
      }

      async function refreshLive() {
        groupData = await api(`/api/groups/${currentGroup.id}`);
        currentSelectedId = live.renderDashboard(groupData, currentSession, currentSelectedId, currentFilter);
        updateNotificationsUI(groupData.expenses);
        updateGroupSwitcher(availableGroups, currentGroup);
        bindSettingsHandlers(currentGroup, groupData.members);
      }

      await refreshLive();

      async function openLiveReview(opener, expenseId) {
        const id = expenseId || currentSelectedId;
        if (!id) return;
        try {
          const expenseDetail = await api(`/api/expenses/${id}`);
          const draft = (expenseDetail.revisions || []).find(r => r.status === "draft");
          let previewData = null;
          if (draft) {
            previewData = await api(`/api/expenses/${id}/preview`, "POST", {
              revision_id: draft.id,
              edit_version: draft.edit_version,
            });
          }
          live.renderReceipt(expenseDetail, previewData, groupData.members);
          openDialog(review, opener);
        } catch (err) {
          console.error("Failed to load receipt review:", err);
        }
      }

      function searchExpenses(opener) {
        openTool("Find an expense", `
          <label class="tool-field">Search expenses<input type="search" placeholder="Transport, dinner, refreshments"></label>
          <div class="tool-results" aria-live="polite"></div>`, opener);
        const query = toolContent.querySelector("input");
        const results = toolContent.querySelector(".tool-results");
        function showResults() {
          const term = query.value.trim().toLowerCase();
          const allEntries = (groupData?.expenses || []).map(entry =>
            live.presentation(entry, groupData.group, currentSession?.demo)
          );
          const matches = allEntries.filter(e =>
            (e.title || e.merchant || "").toLowerCase().includes(term) ||
            (term.includes("refresh") && (e.merchant || "").toLowerCase().includes("refresh")) ||
            (term.includes("dinner") && (e.title || "").toLowerCase().includes("dinner"))
          );
          results.replaceChildren();
          if (!matches.length) {
            results.textContent = "No expenses match this search.";
            return;
          }
          for (const row of matches) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "tool-button";
            button.textContent = row.title || row.merchant;
            button.addEventListener("click", async () => {
              currentSelectedId = row.id;
              currentFilter = "all";
              await refreshLive();
              tool.close();
            });
            results.append(button);
          }
        }
        query.addEventListener("input", showResults);
        showResults();
        query.focus();
      }

      function addMember(opener) {
        openTool("Add member", `
          <form class="tool-form" id="live-invite-form">
            <label class="tool-field">Email<input name="email" type="email" autocomplete="email" required></label>
            <div class="tool-actions"><button type="submit" class="tool-button">Create invitation</button></div>
          </form>
          <div id="invite-result"></div>
        `, opener);
        const form = toolContent.querySelector("form");
        form.querySelector("input").focus();
        form.addEventListener("submit", async event => {
          event.preventDefault();
          const email = form.querySelector("input").value.trim();
          try {
            const inviteRes = await api(`/api/groups/${currentGroup.id}/invites`, "POST", { email });
            const inviteUrl = inviteRes.path;
            toolContent.querySelector("#invite-result").innerHTML = `
              <p>Invitation created:</p>
              <p><a class="tool-button" href="${inviteUrl}">${inviteUrl}</a></p>
            `;
          } catch (err) {
            toolContent.querySelector("#invite-result").innerHTML = `<p class="error">${err.message}</p>`;
          }
        });
      }

      function uploadReceipt(opener) {
        openTool("Upload receipt", `
          <form class="tool-form" id="live-upload-form">
            <label class="tool-field">Choose a receipt<input type="file" name="receipt" accept="image/jpeg,image/png,application/pdf" required></label>
            <div class="tool-actions"><button type="submit" class="tool-button">Upload receipt</button></div>
            <p role="status"></p>
          </form>
        `, opener);
        const form = toolContent.querySelector("form");
        const picker = form.querySelector("input");
        picker.addEventListener("change", () => {
          const file = picker.files[0];
          toolContent.querySelector("[role=status]").textContent = file ? `Selected: ${file.name}` : "";
        });
        form.addEventListener("submit", async event => {
          event.preventDefault();
          const statusEl = toolContent.querySelector("[role=status]");
          statusEl.textContent = "Uploading...";
          try {
            const formData = new FormData(form);
            const res = await api(`/api/groups/${currentGroup.id}/receipts`, "POST", formData);
            tool.close();
            window.location.href = `/workspace?group=${currentGroup.id}#expense/${res.expense_id}`;
          } catch (err) {
            statusEl.textContent = err.message;
          }
        });
      }

      async function addExpense() {
        try {
          const res = await api(`/api/groups/${currentGroup.id}/expenses`, "POST", {});
          window.location.href = `/workspace?group=${currentGroup.id}#expense/${res.id}`;
        } catch (err) {
          console.error("Failed to create expense draft:", err);
        }
      }

      function createNewGroup(opener) {
        openTool("Create a new group", `
          <form class="tool-form" id="create-group-form">
            <label class="tool-field">Group Name<input name="name" maxlength="80" placeholder="e.g. Goa Trip '26" required></label>
            <label class="tool-field">Description<input name="description" placeholder="College trip expenses"></label>
            <div class="tool-actions"><button type="submit" class="tool-button">Create group</button></div>
          </form>
        `, opener);
        const form = toolContent.querySelector("form");
        form.querySelector("input").focus();
        form.addEventListener("submit", async event => {
          event.preventDefault();
          const name = form.querySelector('[name="name"]').value.trim();
          const description = form.querySelector('[name="description"]').value.trim();
          try {
            const res = await api("/api/groups", "POST", { name, description });
            tool.close();
            window.location.href = `/static/jaipur/index.html?group=${res.id}`;
          } catch (err) {
            openTool("Error", `<p class="error">${err.message}</p>`, opener);
          }
        });
      }

      document.addEventListener("click", async event => {
        const notifContainer = document.querySelector("#notice-container");
        const notifDropdown = document.querySelector("#notifications-dropdown");
        const groupSwitch = document.querySelector("#group-switch");
        const crumbToggle = document.querySelector("#crumb-group-toggle");
        const groupDropdown = document.querySelector("#group-dropdown");

        if (notifDropdown && !notifDropdown.hidden && !notifContainer?.contains(event.target)) {
          toggleNotifications(false);
        }

        if (groupDropdown && !groupDropdown.hidden && !groupSwitch?.contains(event.target) && !crumbToggle?.contains(event.target)) {
          toggleGroupDropdown(false);
        }

        const button = event.target.closest("button, a");
        const row = event.target.closest("[data-expense]");

        if (button?.id === "group-toggle" || button?.id === "crumb-group-toggle") {
          toggleGroupDropdown();
          return;
        }

        const groupItem = button?.closest("[data-group-select-id], [data-group-name]");
        if (groupItem) {
          const gid = groupItem.dataset.groupSelectId;
          const gname = groupItem.dataset.groupName;
          const target = availableGroups.find(g => (gid && String(g.id) === gid) || (gname && g.name === gname));
          if (target) {
            toggleGroupDropdown(false);
            currentGroup = target;
            currentSelectedId = null;
            const newUrl = new URL(location.href);
            newUrl.searchParams.set("group", target.id);
            history.pushState(null, "", newUrl);
            await refreshLive();
          }
          return;
        }

        if (button?.dataset.filter) {
          currentFilter = button.dataset.filter;
          await refreshLive();
          return;
        }

        if (button?.dataset.select) {
          currentSelectedId = Number(button.dataset.select);
          await refreshLive();
          return;
        }

        if (button?.dataset.action) {
          const action = button.dataset.action;
          if (action === "review") {
            toggleNotifications(false);
            const rid = button.dataset.receipt ? Number(button.dataset.receipt) : currentSelectedId;
            openLiveReview(button, rid);
          } else if (action === "edit-receipt") {
            const rid = button.dataset.receipt ? Number(button.dataset.receipt) : currentSelectedId;
            window.location.href = `/workspace?group=${currentGroup.id}#expense/${rid}`;
          } else if (action === "close-review") {
            review.close();
          } else if (action === "close-tool") {
            tool.close();
          } else if (action === "add-expense") {
            await addExpense();
          } else if (action === "add-member" || action === "settings-add-member") {
            addMember(button);
          } else if (action === "upload-receipt" || action === "upload") {
            uploadReceipt(button);
          } else if (action === "search") {
            searchExpenses(button);
          } else if (action === "notifications") {
            toggleNotifications();
          } else if (action === "toggle-fullscreen") {
            document.body.classList.toggle("force-fullscreen");
            if (!document.fullscreenElement) {
              document.documentElement.requestFullscreen?.().catch(() => {});
            } else {
              document.exitFullscreen?.().catch(() => {});
            }
          } else if (action === "profile") {
            openTool("Your profile", "<p>Aman Sharma · Trip Organizer (Jaipur Industrial Visit)</p>", button);
          } else if (action === "settings") {
            switchView("settings");
          } else if (action === "back-to-overview") {
            switchView("overview");
          } else if (action === "new-group") {
            toggleGroupDropdown(false);
            createNewGroup(button);
          } else if (action === "logout") {
            openTool("Demo workspace", "<p>You’re viewing the shared Jaipur group dashboard.</p>", button);
          }
          return;
        }

        if (button?.dataset.nav) {
          const nav = button.dataset.nav;
          if (nav === "overview") {
            switchView("overview");
            document.querySelector("main")?.focus();
          } else if (nav === "settings") {
            switchView("settings");
          } else if (nav === "ai-guide") {
            switchView("ai-guide");
          } else if (["expenses", "receipts", "balances", "fund", "members"].includes(nav)) {
            window.location.href = `/workspace?group=${currentGroup.id}#${nav}`;
          }
          return;
        }

        if (row && !button) {
          currentSelectedId = Number(row.dataset.expense);
          await refreshLive();
        }
      });

      document.addEventListener("keydown", async event => {
        if (event.key === "Escape") {
          toggleNotifications(false);
          toggleGroupDropdown(false);
        }
        if (event.key === "Enter") {
          const selectBtn = event.target.closest("[data-select]");
          if (selectBtn) {
            currentSelectedId = Number(selectBtn.dataset.select);
            await refreshLive();
          }
        }
      });

      for (const dialog of [review, tool]) {
        dialog.addEventListener("click", event => {
          if (event.target !== dialog) return;
          const { left, right, top, bottom } = dialog.getBoundingClientRect();
          if (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom) {
            dialog.close();
          }
        });
        dialog.addEventListener("close", () => {
          const target = returnFocus.get(dialog);
          if (!review.open && !tool.open && target?.isConnected && !target.closest("[hidden]")) target.focus();
        });
      }

    } catch (err) {
      console.warn("Live mode failed to load:", err);
      initStatic();
    }
  }

  function initStatic() {
    const expenses = [...document.querySelectorAll("[data-expense]")];
    const filters = [...document.querySelectorAll("button[data-filter]")];
    const emptyFeed = document.querySelector("#feed-empty");
    const review = document.querySelector("#receipt-review");
    const tool = document.querySelector("#dashboard-tool");
    const toolTitle = document.querySelector("#tool-title");
    const toolContent = document.querySelector("#tool-content");
    const returnFocus = new WeakMap();
    const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });

    let filter = "all";
    let selected = expenses.find(row => row.classList.contains("is-selected")) || expenses[0];

    function updateFeed() {
      const visible = expenses.filter(row => filter === "all" || row.dataset.status === filter);
      const active = visible.includes(selected) ? selected : visible[0];
      for (const row of expenses) {
        row.hidden = !visible.includes(row);
        row.classList.toggle("is-selected", row === active);
        row.querySelector("[data-select]")?.setAttribute("aria-pressed", String(row === active));
      }
      for (const button of filters) {
        const current = button.dataset.filter === filter;
        button.classList.toggle("is-active", current);
        button.setAttribute("aria-pressed", String(current));
      }
      if (emptyFeed) emptyFeed.hidden = visible.length !== 0;
    }

    function selectExpense(id, reveal = false) {
      const row = expenses.find(expense => expense.dataset.expense === id);
      if (!row) return;
      if (reveal && row.hidden) filter = "all";
      selected = row;
      updateFeed();
      return row.querySelector("[data-select]");
    }

    function heading(row) {
      return row.querySelector("[data-expense-title], h2, h3")?.textContent.trim() || row.dataset.expense;
    }

    function expenseAmount(row) {
      return row.querySelector("[data-expense-amount], .expense-amount")?.textContent.trim();
    }

    function openDialog(dialog, opener) {
      if (dialog.open) return;
      returnFocus.set(dialog, opener);
      dialog.showModal();
    }

    function openTool(title, markup, opener) {
      toolTitle.textContent = title;
      toolContent.innerHTML = markup;
      openDialog(tool, opener);
    }

    function note(text) {
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      toolContent.replaceChildren(paragraph);
    }

    function openReview(opener, id = "dinner") {
      const row = expenses.find(expense => expense.dataset.expense === id);
      if (id !== "dinner" && row) {
        openTool(heading(row), "<p></p>", opener);
        const amount = expenseAmount(row);
        note(amount ? `Settled · ${amount}` : "This expense is settled.");
        return;
      }
      selectExpense("dinner", true);
      const origin = tool.open ? returnFocus.get(tool) : opener;
      if (tool.open) tool.close();
      openDialog(review, origin);
    }

    function formTool(title, fields, submitLabel, opener, submit) {
      openTool(title, `<form class="tool-form">${fields}
        <div class="tool-actions"><button type="submit" class="tool-button">${submitLabel}</button></div>
      </form>`, opener);
      const form = toolContent.querySelector("form");
      form.querySelector("input, select")?.focus();
      form.addEventListener("submit", event => {
        event.preventDefault();
        submit(new FormData(form));
      });
    }

    function addExpense(opener) {
      formTool("Add expense", `
        <label class="tool-field">Expense name<input name="name" maxlength="80" required></label>
        <label class="tool-field">Amount (₹)<input name="amount" type="number" inputmode="decimal" min="0.01" step="0.01" required></label>
        <label class="tool-field">Category
          <select name="category"><option>Transport</option><option>Food</option><option>Other</option></select>
        </label>`, "Preview expense", opener, data => {
        toolTitle.textContent = "Expense preview";
        note(`${data.get("name")} · ${data.get("category")} · ${currency.format(Number(data.get("amount")))}`);
      });
    }

    function addMember(opener) {
      formTool("Add member", `
        <label class="tool-field">Name<input name="name" maxlength="80" autocomplete="name" required></label>
        <label class="tool-field">Email<input name="email" type="email" autocomplete="email" required></label>
      `, "Preview invitation", opener, data => {
        toolTitle.textContent = "Invitation preview";
        note(`${data.get("name")} · ${data.get("email")} · Jaipur Industrial Visit`);
      });
    }

    function searchExpenses(opener) {
      openTool("Find an expense", `
        <label class="tool-field">Search expenses<input type="search" placeholder="Transport, dinner, refreshments"></label>
        <div class="tool-results" aria-live="polite"></div>`, opener);
      const query = toolContent.querySelector("input");
      const results = toolContent.querySelector(".tool-results");
      function showResults() {
        const term = query.value.trim().toLowerCase();
        const matches = expenses.filter(row => heading(row).toLowerCase().includes(term));
        results.replaceChildren();
        if (!matches.length) {
          results.textContent = "No expenses match this search.";
          return;
        }
        for (const row of matches) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "tool-button";
          button.textContent = heading(row);
          button.addEventListener("click", () => {
            const target = selectExpense(row.dataset.expense, true);
            returnFocus.set(tool, target);
            tool.close();
          });
          results.append(button);
        }
      }
      query.addEventListener("input", showResults);
      showResults();
      query.focus();
    }

    function uploadReceipt(opener) {
      openTool("Upload receipt", `
        <label class="tool-field">Choose a receipt<input type="file" accept="image/jpeg,image/png,application/pdf"></label>
        <p role="status"></p>`, opener);
      const picker = toolContent.querySelector("input");
      picker.addEventListener("change", () => {
        const file = picker.files[0];
        toolContent.querySelector("[role=status]").textContent = file ? `Selected: ${file.name}` : "";
      });
      picker.focus();
    }

    function focusSection(selector) {
      const section = document.querySelector(selector);
      if (!section) return;
      const target = section.querySelector("h1, h2, h3") || section;
      target.tabIndex = -1;
      target.focus();
    }

    const actions = {
      review: button => openReview(button, button.dataset.receipt),
      "close-review": () => review.close(),
      "close-tool": () => tool.close(),
      "add-expense": addExpense,
      "add-member": addMember,
      "upload-receipt": uploadReceipt,
      upload: uploadReceipt,
      search: searchExpenses,
      "expenses-search": searchExpenses,
      notifications: () => toggleNotifications(),
      "toggle-fullscreen": () => {
        document.body.classList.toggle("force-fullscreen");
        if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
        else document.exitFullscreen?.().catch(() => {});
      },
      profile: button => openTool("Your profile", "<p>Jaipur Industrial Visit · Group member</p>", button),
      settings: () => switchView("settings"),
      "back-to-overview": () => switchView("overview"),
      "settle-simran": button => {
        openTool("Record Settlement", "<p>Payment of <strong>₹262.50</strong> from <strong>Simran</strong> to <strong>Aman</strong> recorded via UPI. Balance updated upon confirmation.</p>", button);
      },
      "settle-karan": button => {
        openTool("Record Settlement", "<p>Payment of <strong>₹315.00</strong> from <strong>Karan</strong> to <strong>Aman</strong> recorded via UPI. Balance updated upon confirmation.</p>", button);
      },
      "fund-contribute": button => {
        openTool("Record Fund Advance", "<p>Record student advance payment into the Jaipur Trip Fund pool.</p>", button);
      },
      "copy-invite": async () => {
        try {
          await navigator.clipboard.writeText(window.location.origin + "/?invite=jaipur-iv-2026");
          note("Invitation link copied to clipboard.");
        } catch {
          note("Invitation link: " + window.location.origin + "/?invite=jaipur-iv-2026");
        }
      },
      "new-group": button => {
        toggleGroupDropdown(false);
        formTool("Create a new group", `
          <label class="tool-field">Group Name<input name="name" maxlength="80" required></label>
          <label class="tool-field">Description<input name="description"></label>
        `, "Create group", button, data => {
          toolTitle.textContent = "Group created";
          note(`Group "${data.get("name")}" created.`);
        });
      },
      logout: button => openTool("Demo workspace", "<p>You’re viewing the shared Jaipur group dashboard.</p>", button),
    };

    const navigation = {
      overview: () => switchView("overview"),
      settings: () => switchView("settings"),
      "ai-guide": () => switchView("ai-guide"),
      expenses: () => { window.location.href = `/workspace?group=${currentGroup?.id || 3}#expenses`; },
      receipts: () => { window.location.href = `/workspace?group=${currentGroup?.id || 3}#receipts`; },
      balances: () => { window.location.href = `/workspace?group=${currentGroup?.id || 3}#balances`; },
      fund: () => { window.location.href = `/workspace?group=${currentGroup?.id || 3}#fund`; },
      members: () => { window.location.href = `/workspace?group=${currentGroup?.id || 3}#members`; },
    };

    document.addEventListener("click", event => {
      const notifContainer = document.querySelector("#notice-container");
      const notifDropdown = document.querySelector("#notifications-dropdown");
      const groupSwitch = document.querySelector("#group-switch");
      const crumbToggle = document.querySelector("#crumb-group-toggle");
      const groupDropdown = document.querySelector("#group-dropdown");

      if (notifDropdown && !notifDropdown.hidden && !notifContainer?.contains(event.target)) {
        toggleNotifications(false);
      }
      if (groupDropdown && !groupDropdown.hidden && !groupSwitch?.contains(event.target) && !crumbToggle?.contains(event.target)) {
        toggleGroupDropdown(false);
      }

      const button = event.target.closest("button, a");
      const row = event.target.closest("[data-expense]");

      if (button?.id === "group-toggle" || button?.id === "crumb-group-toggle") {
        toggleGroupDropdown();
        return;
      }

      const groupItem = button?.closest("[data-group-name]");
      if (groupItem) {
        const name = groupItem.dataset.groupName;
        const activeLabel = document.querySelector("#active-group-label");
        const crumbName = document.querySelector("#crumb-group-name");
        if (activeLabel) activeLabel.textContent = name;
        if (crumbName) crumbName.textContent = name;
        document.querySelectorAll(".group-item").forEach(item => {
          item.classList.toggle("is-selected", item === groupItem);
        });
        toggleGroupDropdown(false);
        return;
      }

      if (button?.dataset.filter) {
        filter = button.dataset.filter;
        updateFeed();
      } else if (button?.dataset.select) {
        selectExpense(button.dataset.select);
      } else if (button?.dataset.action) {
        actions[button.dataset.action]?.(button);
      } else if (button?.dataset.nav) {
        navigation[button.dataset.nav]?.(button);
      } else if (row && !button) {
        selectExpense(row.dataset.expense);
      }
    });

    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        toggleNotifications(false);
        toggleGroupDropdown(false);
      }
    });

    const exportBtn = document.querySelector("#btn-export-json");
    if (exportBtn) {
      exportBtn.onclick = () => {
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({ demo: "Jaipur Industrial Visit" }, null, 2));
        const downloadAnchor = document.createElement("a");
        downloadAnchor.setAttribute("href", dataStr);
        downloadAnchor.setAttribute("download", "thrive-group-demo.json");
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();
      };
    }
    const printBtn = document.querySelector("#btn-print-report");
    if (printBtn) printBtn.onclick = () => window.print();

    const form = document.querySelector("#settings-profile-form");
    if (form) {
      form.onsubmit = e => {
        e.preventDefault();
        const fb = document.querySelector("#settings-feedback");
        if (fb) {
          fb.textContent = "✓ Settings saved.";
          setTimeout(() => { fb.textContent = ""; }, 3000);
        }
      };
    }

    for (const dialog of [review, tool]) {
      dialog.addEventListener("click", event => {
        if (event.target !== dialog) return;
        const { left, right, top, bottom } = dialog.getBoundingClientRect();
        if (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom) {
          dialog.close();
        }
      });
      dialog.addEventListener("close", () => {
        const target = returnFocus.get(dialog);
        if (!review.open && !tool.open && target?.isConnected && !target.closest("[hidden]")) target.focus();
      });
    }

    updateFeed();
    initInteractiveCalc();
  }
})();
