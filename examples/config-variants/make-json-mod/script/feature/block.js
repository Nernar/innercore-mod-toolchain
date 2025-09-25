const BLOCK_TYPE_RADIACTIVE_LOG = Block.createSpecialType({
	base: 1,
	solid: true,
	renderlayer: EBlockRenderLayer.BLEND,
	lightopacity: 7,
	explosionres: 4.0,
	translucency: 1.0,
	lightlevel: 15,
	sound: "wood"
});

IDRegistry.genBlockID("oxidized_log");
Block.createBlock("oxidized_log", [{
	name: "Oxidized Log",
	texture: [
		["oxidized_log_top", 0],
		["oxidized_log_top", 0],
		["oxidized_log_side", 0]
	],
	inCreative: true
}, {
	name: "Oxidized Log",
	texture: [
		["oxidized_log_side", 1],
		["oxidized_log_side", 1],
		["oxidized_log_top", 0],
		["oxidized_log_top", 0],
		["oxidized_log_side", 1]
	],
	inCreative: true
}, {
	name: "Oxidized Log",
	texture: [
		["oxidized_log_side", 1],
		["oxidized_log_side", 1],
		["oxidized_log_side", 1],
		["oxidized_log_side", 1],
		["oxidized_log_top", 0]
	],
	inCreative: true
}], BLOCK_TYPE_RADIACTIVE_LOG);

Callback.addCallback("ItemUse", function(coords, item, block, isExternal, playerUid) {
    if (block.id == BlockID.oxidized_log) {
        let source = BlockSource.getDefaultForActor(playerUid);
        if (source != null) {
            let data = source.getBlockData(coords.x, coords.y, coords.z);
            source.setBlock(coords.x, coords.y, coords.z, BlockID.oxidized_log, data >= 2 ? 0 : ++data);
        }
    }
});
