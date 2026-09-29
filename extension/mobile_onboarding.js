// First-install onboarding for mobile Firefox.
(function (root) {
  "use strict";

  const SETUP_PAGE = "options.html#daemon-connection";
  const COMPLETED_KEY = "mobile_onboarding_completed";

  function shouldOpen(details, platformInfo) {
    return Boolean(
      details &&
      details.reason === "install" &&
      platformInfo &&
      platformInfo.os === "android"
    );
  }

  function openOnFirstAndroidInstall(chromeApi, details) {
    if (!details || details.reason !== "install") return;
    if (!chromeApi || !chromeApi.runtime || !chromeApi.tabs) return;
    if (typeof chromeApi.runtime.getPlatformInfo !== "function") return;

    let handled = false;
    function onPlatformInfo(platformInfo) {
      if (handled) return;
      handled = true;
      if (chromeApi.runtime.lastError || !shouldOpen(details, platformInfo)) return;

      const storage = chromeApi.storage && chromeApi.storage.local;
      if (!storage || typeof storage.get !== "function" || typeof storage.set !== "function") {
        chromeApi.tabs.create({ url: chromeApi.runtime.getURL(SETUP_PAGE), active: true });
        return;
      }
      storage.get(COMPLETED_KEY, (values) => {
        if (chromeApi.runtime.lastError || (values && values[COMPLETED_KEY])) return;
      let settled = false;
      const markOpened = () => {
        if (settled) return;
        if (chromeApi.runtime.lastError) {
          settled = true;
          return;
        }
        settled = true;
        storage.set({ [COMPLETED_KEY]: true });
      };
      const markFailed = () => {
        settled = true;
      };
      try {
        const result = chromeApi.tabs.create(
          { url: chromeApi.runtime.getURL(SETUP_PAGE), active: true },
          markOpened
        );
        if (result && typeof result.then === "function") {
          result.then(markOpened, markFailed);
        }
      } catch (_) {
        markFailed();
      }
      });
    }

    try {
      const result = chromeApi.runtime.getPlatformInfo(onPlatformInfo);
      if (result && typeof result.then === "function") result.then(onPlatformInfo, () => {});
    } catch (_) { /* unavailable platform API means no onboarding */ }
  }

  root.SleeperMobileOnboarding = { SETUP_PAGE, COMPLETED_KEY, shouldOpen, openOnFirstAndroidInstall };
})(typeof globalThis !== "undefined" ? globalThis : this);
