import json
import platform
import shutil
import subprocess
from os.path import dirname, isdir, isfile, join
from typing import Any, Dict, List, Optional

from .context import GLOBALS
from .logger import debug, failure, success, warn

BABEL_CONFIG_NAMES = (
	"babel.config.json",
	"babel.config.js",
	"babel.config.cjs",
	"babel.config.mjs",
	".babelrc",
	".babelrc.json",
	".babelrc.js",
	".babelrc.cjs",
)

BABEL_PACKAGES = [
	"@babel/core",
	"@babel/cli",
	"@babel/preset-typescript",
	"@babel/preset-env",
	"@babel/plugin-proposal-decorators",
]

RHINO_TARGET_VERSION = "1.7.13"

def get_local_node_dir() -> Optional[str]:
	custom_node = GLOBALS.TOOLCHAIN_CONFIG.get_value("tools.node")
	from .output_directory import get_config_directory
	local_node = custom_node if custom_node else join(get_config_directory(), "node")
	return local_node if isdir(local_node) else None

def get_npm_path() -> Optional[str]:
	local_node = get_local_node_dir()
	if local_node:
		ext = ".cmd" if platform.system() == "Windows" else ""
		local_npm = join(local_node, "npm" + ext)
		if platform.system() != "Windows":
			local_npm = join(local_node, "bin", "npm")
		if isfile(local_npm):
			return local_npm
	return shutil.which("npm")

def request_babel(only_check: bool = False) -> Optional[str]:
	if GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
		return None

	ext = ".cmd" if platform.system() == "Windows" else ""

	local_node = get_local_node_dir()
	if local_node:
		# Looking in global npm installation for babel
		local_babel = join(local_node, "babel" + ext)
		if platform.system() != "Windows":
			local_babel = join(local_node, "bin", "babel")
		if isfile(local_babel):
			return local_babel

		# Looking in local npm installation for babel
		local_babel_bin = join(local_node, "node_modules", ".bin", "babel" + ext)
		if isfile(local_babel_bin):
			return local_babel_bin

	babel = shutil.which("babel")
	if babel:
		return babel

	if only_check:
		return None

	from .shell import confirm_prompt
	if not confirm_prompt("Babel is not installed. Do you want to install it for faster TypeScript transpilation?", True):
		return None

	npm = get_npm_path()
	if not npm:
		warn("npm not found. Please install Node.js via components.")
		return None

	return install_babel(npm)

def install_babel(npm: str) -> Optional[str]:
	from .output_directory import get_config_directory
	install_prefix = join(get_config_directory(), "node")

	debug(f"Installing Babel packages via npm into {install_prefix!r}...")
	result = subprocess.call(
		[npm, "install", "--prefix", install_prefix] + BABEL_PACKAGES,
		shell=platform.system() == "Windows"
	)

	if result != 0:
		failure("Failed to install Babel packages. Check your npm/Node.js installation.")
		return None

	success("Babel packages installed successfully.")
	return request_babel(only_check=True)

def has_project_babel_config(directory: str) -> bool:
	project_root = GLOBALS.MAKE_CONFIG.directory
	current = directory

	while current and current != dirname(project_root) and current != dirname(current):
		for config_name in BABEL_CONFIG_NAMES:
			if isfile(join(current, config_name)):
				return True
		if current == project_root:
			break
		current = dirname(current)
	return False

def convert_tsconfig_to_babel_plugins(tsconfig_params: Dict[str, Any]) -> List[Any]:
	plugins: List[Any] = []
	if tsconfig_params.get("experimentalDecorators", False) is True:
		plugins.append(["@babel/plugin-proposal-decorators", { "version": "legacy" }])
	return plugins

def generate_toolchain_babel_config(output_path: str, tsconfig_params: Optional[Dict[str, Any]] = None) -> str:
	params: Dict[str, Any] = dict(tsconfig_params) if tsconfig_params else {}

	if "experimentalDecorators" not in params:
		params["experimentalDecorators"] = GLOBALS.TSCONFIG_TOOLCHAIN.get("experimentalDecorators", True)

	plugins = convert_tsconfig_to_babel_plugins(params)
	config: Dict[str, Any] = {
		"presets": [
			["@babel/preset-typescript", {
				"allExtensions": True,
				"isTSX": False,
			}],
			["@babel/preset-env", {
				"targets": {"rhino": RHINO_TARGET_VERSION},
				"modules": False,
			}],
		],
		"plugins": plugins,
	}

	with open(output_path, "w", encoding="utf-8") as f:
		f.write(json.dumps(config, indent="\t", ensure_ascii=False) + "\n")

	return output_path
