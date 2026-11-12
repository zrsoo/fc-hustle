/* Narrow public persona projection. No identity, club, session or credential data. */
(() => {
  "use strict";
  if (window.__fcDiscoveryPersonaFollowupV1) return;
  const publicPlatforms = new Set(["PC", "pc", "PSN", "XBL", "SWI", "ps3", "ps4", "ps5",
    "xbox", "xbox360", "xboxone", "xbsx", "switch", ""]);
  function classify(persona, nativePC) {
    if (!persona || typeof persona !== "object" || Array.isArray(persona) ||
        Object.prototype.toString.call(persona) !== "[object Object]") return null;
    try {
      const platform = persona.platform, flag = persona.isPC;
      if (flag !== undefined && typeof flag !== "boolean") return null;
      // EA UTPersonaEntity derives these getters from its selected club. The
      // public GamePlatform enum defines PC as uppercase "PC", not "pc".
      if (platform === "PC") return nativePC === "PC" && flag === true ? "pc" : null;
      if (platform === "pc") return flag !== false ? "pc" : null;
      if (platform == null) return flag === true ? "pc" : null;
      // A true flag never overrides an explicit unknown or console platform.
      return null;
    } catch { return null; }
  }
  function selected() {
    return typeof services === "undefined" ? null : services.User?.getUser?.()?.getSelectedPersona?.();
  }
  function nativePC() {
    return typeof GamePlatform === "undefined" ? undefined : GamePlatform.PC;
  }
  function selectedPlatform() {
    try { return classify(selected(), nativePC()); } catch { return null; }
  }
  function inspect() {
    const out = {schema: 1, persona_present: false, platform_type: "missing", platform_value: null,
      is_pc_type: "missing", is_pc: null, native_pc_constant: null, accepted: false, read_error: false};
    try {
      const persona = selected(), pc = nativePC();
      out.native_pc_constant = pc === "PC" ? pc : null;
      if (!persona || typeof persona !== "object" || Array.isArray(persona) ||
          Object.prototype.toString.call(persona) !== "[object Object]") return out;
      out.persona_present = true;
      const platform = persona.platform, flag = persona.isPC;
      out.platform_type = platform === undefined ? "missing" : platform === null ? "null" :
        typeof platform === "string" ? "string" : "invalid";
      out.platform_value = publicPlatforms.has(platform) ? platform : null;
      out.is_pc_type = flag === undefined ? "missing" : typeof flag === "boolean" ? "boolean" : "invalid";
      out.is_pc = typeof flag === "boolean" ? flag : null;
      out.accepted = classify(persona, pc) === "pc";
    } catch { out.read_error = true; }
    return out;
  }
  Object.defineProperty(window, "__fcDiscoveryPersonaFollowupV1", {
    value: Object.freeze({classify, selectedPlatform, inspect})
  });
})();
