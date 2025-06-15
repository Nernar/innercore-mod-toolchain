from abc import ABCMeta, abstractmethod
from functools import lru_cache
from typing import Dict, MutableSequence, MutableSet, Optional

from .config import Config
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
TOOLCHAIN_RULE_SET.append_set("native_architecture", "arm", "arm64", "x86", "x86_64")

class RuleSetHolder(metaclass=ABCMeta):
	rule_set: RuleSet
	properties: MutableSequence[str]

	def __init__(self, rule_set: Optional[RuleSet] = None) -> None:
		self.rule_set = rule_set or TOOLCHAIN_RULE_SET
		self.properties = []

	def is_relevant_configuration(self, value_set: str, allow_unresolved_properties: bool = True) -> bool:
		return self.rule_set.is_relevant(self.properties, value_set, allow_unresolved_properties=allow_unresolved_properties)

	def bisect_properties(self, *properties: str) -> None:
		self.rule_set.bisect_values(self.properties, *properties)

	def remove_rules(self, *rules: str) -> None:
		self.rule_set.remove_rules(self.properties, *rules)

@lru_cache(maxsize=4096)
def get_rule_set_config(type: Optional[type['Config']]):
	if not type:
		type = Config
	class RuleSetConfig(type, RuleSetHolder):
		pass
	return RuleSetConfig
