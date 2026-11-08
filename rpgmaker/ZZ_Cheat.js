//=============================================================================
// ZZ_Cheat.js  (RPG Maker MV / MZ)
//=============================================================================
/*:
 * @target MZ
 * @plugindesc Trucos: oro máximo, nivel máximo, daño máximo y galería desbloqueada.
 *
 * @param gold
 * @text Oro máximo (1 = sí)
 * @default 0
 *
 * @param level
 * @text Nivel máximo a los personajes (1 = sí)
 * @default 0
 *
 * @param dmg
 * @text Daño máximo de los aliados (1 = sí)
 * @default 0
 *
 * @param stills
 * @text Desbloquear My_StillsGallery (1 = sí)
 * @default 0
 *
 * @param switches
 * @text Interruptores a activar (lista JSON de números)
 * @default []
 */
(() => {
    "use strict";
    const p = PluginManager.parameters("ZZ_Cheat");
    const on = k => String(p[k] || "0") === "1";
    const switches = JSON.parse(p.switches || "[]").map(Number);
    const MAX_DAMAGE = 99999999;

    function applyCheats() {
        if (!$gameParty || !$gameSwitches || !$gameActors) return;
        switches.forEach(id => $gameSwitches.setValue(id, true));

        if (on("gold")) {
            const falta = $gameParty.maxGold() - $gameParty.gold();
            if (falta > 0) $gameParty.gainGold(falta);
        }
        if (on("level")) {
            $gameActors._data.forEach(a => {
                if (a && a.level < a.maxLevel()) a.changeLevel(a.maxLevel(), false);
            });
        }
        if (on("stills") && window.MyStillsGallery) {
            const sp = PluginManager.parameters("My_StillsGallery");
            let src = [];
            try { src = JSON.parse(sp.stills || "[]"); } catch (e) { /* sin lista */ }
            src.forEach((entry, i) => {
                let d = entry;
                if (typeof entry === "string") { try { d = JSON.parse(entry); } catch (e) { d = {}; } }
                window.MyStillsGallery.markViewed(String((d && d.id) || i + 1));
            });
        }
    }

    const _mapStart = Scene_Map.prototype.start;
    Scene_Map.prototype.start = function () {
        _mapStart.call(this);
        applyCheats();
    };

    if (on("dmg")) {
        const _makeDamage = Game_Action.prototype.makeDamageValue;
        Game_Action.prototype.makeDamageValue = function (target, critical) {
            const v = _makeDamage.call(this, target, critical);
            if (v > 0 && this.subject().isActor() && target.isEnemy()) return MAX_DAMAGE;
            return v;
        };
    }
})();
