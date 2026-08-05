import json
import os
import platform
import subprocess
from glob import glob
from os.path import dirname, exists, isdir, join, relpath
from typing import Any, Dict, List

from .context import GLOBALS, PROPERTIES
from .includes import Includes

# The TypeScript Compiler - Version 4.8.3
TSCONFIG: Dict[str, Any] = {
	# JavaScript Support
	"allowJs": False,
	"checkJs": False,
	"maxNodeModuleJsDepth": 0,

	# Interop Constraints
	"allowSyntheticDefaultImports": False,
	"esModuleInterop": False,
	"forceConsistentCasingInFileNames": False,
	"isolatedModules": False,
	"preserveSymlinks": False,

	# Modules
	"allowUmdGlobalAccess": False,
	"baseUrl": None,
	"module": None,
	"moduleResolution": "classic",
	"moduleSuffixes": [],
	"noResolve": False,
	"paths": [],
	"resolveJsonModule": False,
	"rootDir": [],
	"rootDirs": [],
	"typeRoots": [],
	"types": [],

	# Type Checking
	"allowUnreachableCode": None,
	"allowUnusedLabels": None,
	"alwaysStrict": False,
	"exactOptionalPropertyTypes": False,
	"noFallthroughCasesInSwitch": False,
	"noImplicitAny": False,
	"noImplicitOverride": False,
	"noImplicitReturns": False,
	"noImplicitThis": False,
	"noPropertyAccessFromIndexSignature": False,
	"noUncheckedIndexedAccess": False,
	"noUnusedLocals": False,
	"noUnusedParameters": False,
	"strict": False,
	"strictBindCallApply": False,
	"strictFunctionTypes": False,
	"strictNullChecks": False,
	"strictPropertyInitialization": False,
	"useUnknownInCatchVariables": False,

	# Watch and Build Modes
	"assumeChangesOnlyAffectDirectDependencies": False,

	# Backwards Compatibility
	# "charset": "utf8",
	"keyofStringsOnly": False,
	"noImplicitUseStrict": False,
	"noStrictGenericChecks": False,
	# "out": None,
	"suppressExcessPropertyErrors": False,
	"suppressImplicitAnyIndexErrors": False,

	# Projects
	"composite": False,
	"disableReferencedProjectLoad": False,
	"disableSolutionSearching": False,
	"disableSourceOfProjectReferenceRedirect": False,
	"incremental": False,
	"tsBuildInfoFile": ".tsbuildinfo",

	# Emit
	"declaration": False,
	"declarationDir": None,
	"declarationMap": False,
	"downlevelIteration": False,
	"emitBOM": False,
	"emitDeclarationOnly": False,
	"importHelpers": False,
	"importsNotUsedAsValues": "remove",
	"inlineSourceMap": False,
	"inlineSources": False,
	"mapRoot": None,
	"newLine": None,
	"noEmit": False,
	"noEmitHelpers": False,
	"noEmitOnError": False,
	"outDir": None,
	"outFile": None,
	"preserveConstEnums": False,
	"preserveValueImports": False,
	"removeComments": False,
	"sourceMap": False,
	"sourceRoot": False,
	"stripInternal": False,

	# Compiler Diagnostics
	"diagnostics": False,
	"explainFiles": False,
	"extendedDiagnostics": False,
	"generateCpuProfile": "profile.cpuprofile",
	"generateTrace": False,
	"listEmittedFiles": False,
	"listFiles": False,
	"traceResolution": False,

	# Editor Support
	"disableSizeLimit": False,
	"plugins": [],

	# Language and Environment
	"emitDecoratorMetadata": False,
	"experimentalDecorators": False,
	"jsx": None,
	"jsxFactory": "React.Fragment",
	"jsxImportSource": "react",
	"lib": [],
	"moduleDetection": "auto",
	"noLib": False,
	"reactNamespace": "React",
	"target": "es3",
	"useDefineForClassFields": False,

	# Output Formatting
	"noErrorTruncation": False,
	"preserveWatchOutput": False,
	"pretty": True,

	# Completeness
	"skipDefaultLibCheck": False,
	"skipLibCheck": False
}

# Will be excluded with toolchain overriden options
TSCONFIG_DEPENDENTS: Dict[str, Any] = {
	"allowSyntheticDefaultImports": "esModuleInterop",
	"alwaysStrict": "strict",
	"noImplicitAny": "strict",
	"noImplicitThis": "strict",
	"strictBindCallApply": "strict",
	"strictFunctionTypes": "strict",
	"strictNullChecks": "strict",
	"strictPropertyInitialization": "strict",
	"incremental": "composite",
	"declaration": "composite"
}

# Basic prototype that will be changed when building
TSCONFIG_TOOLCHAIN: Dict[str, Any] = {
	"incremental": True,
	"lib": ["es5", "es2015.core", "es2015.generator"],
	"skipDefaultLibCheck": True,
	"experimentalDecorators": True,
	"noEmitOnError": True,
	"stripInternal": True,
	"allowJs": True
}

class CompositeProject:
	references: List[Dict[str, Any]]
	sources: List[str]

	def __init__(self, path) -> None:
		self.path = path
		self.references = []
		self.sources = []

	def get_tsconfig(self) -> str:
		return GLOBALS.MAKE_CONFIG.get_relative_path(self.path)

	def coerce(self, path: str) -> None:
		path = relpath(path, GLOBALS.MAKE_CONFIG.directory)
		if path in self.sources:
			return
		self.sources.append(path)

	def reference(self, path: str, **kwargs: Any) -> None:
		path = relpath(path, GLOBALS.MAKE_CONFIG.directory)
		for ref in self.references:
			if ref["path"] == path:
				return
		self.references.append({
			"path": path,
			**kwargs
		})

	def has_sources(self) -> bool:
		return len(self.sources) > 0 or len(self.references) > 0

	def requires_composite(self) -> bool:
		return len(self.references) > 0

	def resolve_declarations(self) -> List[str]:
		includes = GLOBALS.MAKE_CONFIG.get_value("declarations", ["declarations"])
		declarations = []
		for filepath in [
			GLOBALS.MAKE_CONFIG.get_path(include) for include in includes
		]:
			if not exists(filepath):
				continue
			if isdir(filepath):
				filepath = join(filepath, "**", "*.d.ts")
			declarations.extend(glob(filepath, recursive=True))
	
		toolchain_declarations = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("declarations")
		if not isdir(toolchain_declarations):
			from .output_directory import get_config_directory
			toolchain_declarations = join(get_config_directory(), "declarations")
		if isdir(toolchain_declarations):
			declarations.extend(glob(join(toolchain_declarations, "**", "*.d.ts"), recursive=True))

		return list(set(declarations))

	def flush(self, **options: Any) -> None:
		template = {
			"compilerOptions": {
				"strict": False,
				"ignoreDeprecations": "6.0",
				**GLOBALS.TSCONFIG_TOOLCHAIN,
				"target": "es5", # Most of ES6 is not realized in Rhino
				"module": "none",
				"outDir": GLOBALS.MAKE_CONFIG.get_build_path("sources"),
				**options
			},
			"exclude": [
				"dom",
				"dom.iterable",
				"es2015.iterable",
				"scripthost",
				"webworker",
				"webworker.importscripts",
				"webworker.iterable"
			],
			"include": self.sources
		}

		declarations = self.resolve_declarations()
		if len(declarations) > 0:
			template["files"] = declarations
		if len(self.references) > 0:
			template["references"] = self.references
		with open(self.get_tsconfig(), "w", encoding="utf-8") as tsconfig:
			tsconfig.write(json.dumps(template, indent="\t", ensure_ascii=False) + "\n")

	def build(self, *args: str, emit: bool = True) -> int:
		from .script_setup import request_typescript
		tsc = request_typescript()
		if not tsc:
			raise RuntimeError("A tsc is required to build project, make sure it is present before calling this function.")
		command = [
			tsc,
			"--build", self.get_tsconfig(),
			*args
		]
		if not emit:
			command.append("--noEmit")
		return subprocess.call(command, shell=platform.system() == "Windows")

	def type_check(self, *args: str) -> int:
		return self.build(*args, emit=False)

###
# Project configs now should be readen before flushing, compared via
# object comparison (to drop comments, whitespace, etc.) and tsconfigs
# in projects itself should contain only specific source options.

# project
	# dev
		# .includes
		# header.ts
		# tsconfig.json (autogenerated)
	# launcher.ts
	# preloader.ts
	# tsconfig.json (autogenerated)

# Build directory configs will contain following structure:
# - Composite configs contains `composite: true` in directories and
# referenced directly in root file which will be used for release builds.
# - Incremental configs does NOT contains it, only `incremental: true`,
# no references, only direct file includes, directories built separately.
# * No separate reference/incremental tsconfig to include launcher.ts or
# preloader.ts, they will be included direcly via `include` property.

# <build_directory>
	# tsc
		# dev
			# composite-tsconfig.json
			# incremental-tsconfig.json
		# composite-tsconfig.json
		# incremental-tsconfig.json
	# sources (output directory in tsconfigs)
###
class ScriptRepository:
	def include_file(self, source_path: str, destination_path: str, language: str):
		pass

	def include_directory(self, includes: Includes, destination_path: str, language: str):
		pass
