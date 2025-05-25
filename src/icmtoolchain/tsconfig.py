import json
import os
import platform
import subprocess
from glob import glob
from os.path import dirname, exists, isdir, join, relpath
from typing import Any, Dict, List

from . import GLOBALS, PROPERTIES
from .utils import request_typescript

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
	"moduleSuffixes": list(),
	"noResolve": False,
	"paths": list(),
	"resolveJsonModule": False,
	"rootDir": list(),
	"rootDirs": list(),
	"typeRoots": list(),
	"types": list(),

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
	"plugins": list(),

	# Language and Environment
	"emitDecoratorMetadata": False,
	"experimentalDecorators": False,
	"jsx": None,
	"jsxFactory": "React.Fragment",
	"jsxImportSource": "react",
	"lib": list(),
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
	"target": "es5", # Most of ES6 is not realized in Rhino 1.7.7
	"lib": ["es5", "es2015.core", "es2015.generator"],
	"module": "none",
	"skipDefaultLibCheck": True,
	"composite": True,
	"downlevelIteration": True,
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
		self.reset()

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

	def reset(self) -> None:
		self.references = list()
		self.sources = list()

	@staticmethod
	def resolve_declarations() -> List[str]:
		includes = GLOBALS.MAKE_CONFIG.get_value("declarations", [
			"declarations"
		])
		declarations = list()
		for filepath in [
			GLOBALS.MAKE_CONFIG.get_path(include) for include in includes
		]:
			if exists(filepath):
				if isdir(filepath):
					filepath = join(filepath, "**", "*.d.ts")
				declarations.extend(glob(filepath, recursive=True))
	
		toolchain_declarations = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("declarations")
		if not isdir(toolchain_declarations):
			from .output_directory import get_config_directory
			toolchain_declarations = join(get_config_directory(), "declarations")
		if isdir(toolchain_declarations):
			declarations.extend(glob(join(toolchain_declarations, "**", "*.d.ts"), recursive=True))

		if not PROPERTIES.get_value("release"):
			for excluded in GLOBALS.MAKE_CONFIG.get_value("debugIncludesExclude", list()):
				if exists(str(excluded).lstrip("/").partition("/")[0]):
					for declaration in glob(excluded, recursive=True):
						if declaration in declarations:
							declarations.remove(declaration)
				else:
					for declaration in glob(join(toolchain_declarations, excluded), recursive=True):
						if declaration in declarations:
							declarations.remove(declaration)
		return list(set(declarations))

	def flush(self, **kwargs: Any) -> None:
		template = {
			"compilerOptions": {
				"outDir": GLOBALS.MAKE_CONFIG.get_build_path("sources"),
				**GLOBALS.TSCONFIG_TOOLCHAIN
			},
			"compileOnSave": False,
			"exclude": [
				"dom",
				"dom.iterable",
				"es2015.iterable",
				"scripthost",
				"webworker",
				"webworker.importscripts",
				"webworker.iterable"
			] + GLOBALS.MAKE_CONFIG.get_value("development.exclude", list()),
			"include": self.sources + GLOBALS.MAKE_CONFIG.get_value("development.include", list()),
			**kwargs
		}

		declarations = CompositeProject.resolve_declarations()
		if len(declarations) > 0:
			template["files"] = declarations
		if len(self.references) > 0:
			template["references"] = self.references
		with open(self.get_tsconfig(), "w", encoding="utf-8") as tsconfig:
			tsconfig.write(json.dumps(template, indent="\t", ensure_ascii=False) + "\n")

	def build(self, *args: str) -> int:
		tsc = request_typescript()
		if not tsc:
			raise RuntimeError("A tsc is required to build project, make sure it is present before calling this function.")
		return subprocess.call([
			tsc,
			"--build", self.get_tsconfig(),
			*GLOBALS.MAKE_CONFIG.get_value("development.tsc", list()),
			*args
		], shell=platform.system() == "Windows")

	def watch(self, *args: str) -> int:
		tsc = request_typescript()
		if not tsc:
			raise RuntimeError("A tsc is required to watch project, make sure it is present before calling this function.")
		try:
			return subprocess.call([
				tsc,
				"--watch",
				*GLOBALS.MAKE_CONFIG.get_value("development.watch", list()),
				*args
			], cwd=dirname(self.get_tsconfig()).replace("/", os.path.sep), shell=platform.system() == "Windows")
		except KeyboardInterrupt:
			return 0
