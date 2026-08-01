from abc import ABC
from itertools import chain
from typing import (Any, Dict, MutableMapping, MutableSequence, MutableSet,
                    Optional)

from .config import Config, ConfigSupportsKeysAndGetItem
from .utils import ensure_not_whitespace


class RuleSet:
	rules: Dict[str, MutableSet[str]]
	values: MutableSet[str]

	def __init__(self, prototype_set: Optional['RuleSet'] = None) -> None:
		self.rules = {}
		self.values = set()
		if prototype_set:
			for rule in prototype_set.rules:
				self.append_set(rule, *prototype_set.rules[rule])

	def append_set(self, rule: str, *values: str) -> None:
		if not rule in self.rules:
			self.rules[rule] = set()
		rules = self.rules[rule]
		for value in values:
			if value in rules:
				continue
			if value in self.values:
				raise ValueError(f"Rule {rule} contains value {value!r} which is already occupied by another rule!")
			rules.add(value)

	def remove_set(self, rule: str) -> None:
		if not rule in self.rules:
			return
		for value in self.rules[rule]:
			self.values.remove(value)
		del self.rules[rule]

	def rule_of(self, value: str) -> Optional[str]:
		if not value in self.values:
			return
		for rule in self.rules:
			for rule_value in self.rules[rule]:
				if value == rule_value:
					return rule

	def contains_rules(self, properties: MutableSequence[str], *rules: str) -> bool:
		for rule in rules:
			if not rule in self.rules:
				return False
			value_resolved = False
			for rule_value in self.rules[rule]:
				if rule_value in properties:
					value_resolved = True
					break
			if not value_resolved:
				return False
		return True

	def bisect_values(self, properties: MutableSequence[str], *values: str) -> None:
		for value in values:
			rule = self.rule_of(value)
			if not rule or not rule in self.rules:
				continue
			for rule_value in self.rules[rule]:
				while rule_value in properties:
					properties.remove(rule_value)
		for value in values:
			properties.append(value)

	def remove_rules(self, properties: MutableSequence[str], *rules: str) -> None:
		for rule in rules:
			if not rule in self.rules:
				continue
			for value in self.rules[rule]:
				while value in properties:
					properties.remove(value)

	def is_relevant(self, properties: MutableSequence[str], value_set: str, allow_unresolved_properties: bool = True) -> bool:
		if not ensure_not_whitespace(value_set) or value_set == "*":
			return True
		values = value_set.split("-")
		for value in values:
			if not value in properties:
				return False
			if not allow_unresolved_properties and not value in self.values:
				# Most likely a console property that cannot be checked here.
				return False
		return True

TOOLCHAIN_RULE_SET = RuleSet()
TOOLCHAIN_RULE_SET.append_set("package_type", "develop", "release")
TOOLCHAIN_RULE_SET.append_set("java_compiler", "javac", "ecj", "gradle")
TOOLCHAIN_RULE_SET.append_set("native_architecture", "arm", "arm64", "x86", "x86_64")
TOOLCHAIN_RULE_SET.append_set("side", "client", "server")

class RuleSetHolder(ABC):
	rule_set: RuleSet
	properties: MutableSequence[str]

	def __init__(self, rule_set: Optional[RuleSet] = None) -> None:
		self.rule_set = rule_set or TOOLCHAIN_RULE_SET
		self.properties = []

	def is_relevant_configuration(self, value_set: str, allow_unresolved_properties: bool = True) -> bool:
		return self.rule_set.is_relevant(self.properties, value_set, allow_unresolved_properties=allow_unresolved_properties)

	def update_properties(self) -> None:
		pass

	def bisect_properties(self, *properties: str) -> None:
		self.rule_set.bisect_values(self.properties, *properties)
		self.update_properties()

	def contains_rules(self, *rules: str) -> bool:
		return self.rule_set.contains_rules(self.properties, *rules)

	def remove_rules(self, *rules: str) -> None:
		self.rule_set.remove_rules(self.properties, *rules)
		self.update_properties()

class RuleSetConfig(Config):
	def __init__(self, map: Optional[ConfigSupportsKeysAndGetItem] = None, defaults: Optional[Config] = None, overrides: Optional[Config] = None):
		super().__init__(map=map, defaults=defaults)
		self.overrides = overrides

	def get_dict_value(self, key: str) -> Any:
		value = super().get_dict_value(key)
		if not self.overrides or not key in self.overrides:
			return value

		overriden_value = self.overrides.get_dict_value(key)
		if isinstance(overriden_value, MutableMapping):
			if not isinstance(value, MutableMapping):
				return overriden_value
			if isinstance(value, RuleSetConfig):
				return value
			if not isinstance(overriden_value, Config):
				overriden_value = Config(overriden_value)
			config = RuleSetConfig(map=value, overrides=overriden_value)
			self.set_value_unsafe(key, config)
			return config

		if isinstance(overriden_value, MutableSequence):
			if not isinstance(value, MutableSequence):
				return overriden_value
			return list(chain(overriden_value, value))
		return overriden_value
