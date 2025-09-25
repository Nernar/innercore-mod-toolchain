let ticking = 0;

Callback.addCallback("LocalTick", function() {
	ticking++;
	if (ticking % 20 == 0) {
		if (ticking == 1200) {
			ticking = 0;
		}
		Game.tipMessage(ticking / 20);
	}
});

Callback.addCallback("LocalLevelLoaded", function() {
	ticking = 0;
});
