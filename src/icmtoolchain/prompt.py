import concurrent.futures
import threading
from abc import ABC, abstractmethod
from typing import (Any, Callable, Dict, Iterable, List, Optional, Sequence,
                    Sized, Tuple, Union, cast)

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import (AnyFormattedText,
                                           merge_formatted_text, to_plain_text)
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.bindings.focus import (focus_next,
                                                       focus_previous)
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (AnyContainer, HSplit, Layout,
                                   ScrollablePane, ScrollOffsets)
from prompt_toolkit.validation import Validator

from .logger import attention, failure, frozen, print, success
from .shell import (Editable, Interactable, Selectable, clear_application,
                    get_toolchain_style, interactive_application,
                    request_application)

_feedback_injection_lock = threading.Lock()


class Feedback(ABC):
	on_pre_request: Optional[Callable[['Feedback'], None]]

	def __init__(self, prompt: AnyFormattedText = "Ooh, was it supposed to be a query here?", fallback: object = None) -> None:
		self.prompt = prompt
		self.fallback = fallback

	@abstractmethod
	def create_content(self) -> AnyContainer:
		...

	@property
	def content(self) -> AnyContainer:
		if not hasattr(self, "_content"):
			self._content = self.create_content()
		return self._content

	def create_layout(self) -> Layout:
		return Layout(self.content)

	@property
	def layout(self) -> Layout:
		if not hasattr(self, "_layout"):
			self._layout = self.create_layout()
		return self._layout

	def create_key_bindings(self) -> KeyBindings:
		bindings = KeyBindings()

		@bindings.add("c-c")
		@bindings.add("<sigint>")
		def _(event: KeyPressEvent) -> None:
			event.app.exit(exception=KeyboardInterrupt())

		return bindings

	@property
	def key_bindings(self) -> KeyBindings:
		if not hasattr(self, "_key_bindings"):
			self._key_bindings = self.create_key_bindings()
		return self._key_bindings

	def create_application(self, bindings: Optional[KeyBindings] = None) -> Application:
		return Application(
			layout=self.layout,
			style=get_toolchain_style(),
			include_default_pygments_style=False,
			key_bindings=self.key_bindings,
			full_screen=False,
			mouse_support=True,
			erase_when_done=True,
		)

	@property
	def application(self) -> Application:
		if not hasattr(self, "_application"):
			self._application = self.create_application()
		return self._application

	def get_result(self) -> Optional[object]:
		self.inform_if_already_busy()
		return self.result if hasattr(self, "result") and self.result is not None else self.fallback

	def pre_run(self) -> None:
		if hasattr(self, "on_pre_request") and self.on_pre_request:
			self.on_pre_request(self)

	def inform_if_already_busy(self) -> None:
		if self.application.is_running and not self.application.is_done:
			raise RuntimeError("Feedback is already requested, you cannot requery it until guest responds to ongoing one.")

	async def request_async(self) -> Any:
		self.inform_if_already_busy()
		self.result = await self.application.run_async(pre_run=self.pre_run)
		return self.result

	def request(self) -> Any:
		self.inform_if_already_busy()
		self.pre_run()
		
		if interactive_application is not None and interactive_application.is_running:
			with _feedback_injection_lock:
				fut = concurrent.futures.Future()
				self._injection_future = fut
				
				# Push layout into global application
				request_application(self.content)
				
				# Wait until user interacts
				self.result = fut.result()
				clear_application(self.content)
				return self.result
		else:
			self.result = self.application.run(pre_run=self.pre_run)
			return self.result

	async def request_async_safe(self, prints_abort: bool = True) -> Any:
		try:
			return await self.request_async()
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				attention("Abort.")
		return self.fallback

	def request_safe(self, prints_abort: bool = True) -> Any:
		try:
			return self.request()
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				attention("Abort.")
		return self.fallback

	def print_result(self, result: object) -> object:
		if result is True:
			success(self.prompt, end=" ")
			print("Yes", style="class:print.answer")
		elif result is False:
			failure(self.prompt, end=" ")
			print("No", style="class:print.answer")
		elif result == self.fallback:
			frozen(self.prompt, end=" ")
			print(result, style="class:print.answer")
		elif isinstance(result, Sized) and len(result) == 0:
			attention(self.prompt, end=" ")
			print("<nope>", style="class:print.answer")
		else:
			success(self.prompt, end=" ")
			if not isinstance(result, str) and isinstance(result, Iterable):
				print(*result, sep=", ", style="class:print.answer")
			else:
				print(result, style="class:print.answer")

	def complete(self, *, result: object = None, print_result: object = None) -> None:
		if hasattr(self, "_application") and self.application.is_running and not self.application.is_done:
			self.application.exit(result=result)
		if hasattr(self, "_injection_future") and not self._injection_future.done():
			self._injection_future.set_result(result)
			
		if result is not None:
			self.print_result(print_result if print_result else result)

class Input(Feedback):
	def __init__(
		self,
		prompt: AnyFormattedText = "How do you feel about typing?",
		hint: Optional[str] = None,
		explanation: AnyFormattedText = None,
		default_text: Optional[str] = None,
		use_hint_as_fallback: bool = True,
		fallback: object = None,
		on_input: Optional[Callable[['Input', str], None]] = None,
		on_validate: Optional[Callable[['Input', str], Optional[bool]]] = None,
		on_accept: Optional[Callable[['Input', str], Optional[bool]]] = None,
	):
		fallback = fallback if fallback is not None else (default_text or hint)
		Feedback.__init__(self, prompt=prompt, fallback=fallback)
		self.control_prompt = prompt
		self.hint = hint
		self.use_hint_as_fallback = use_hint_as_fallback
		self.explanation = explanation
		self.default_text = default_text
		self.on_input = on_input
		self.on_validate = on_validate
		self.on_accept = on_accept or on_validate
		self.read_only = False

	def create_content(self) -> AnyContainer:
		self.input_control = Editable(
			prompt=self.control_prompt,
			text=self.default_text or "",
			hint=self.hint,
			use_hint_as_fallback=self.use_hint_as_fallback,
			on_text_changed=self.on_text_changed,
			validator=Validator.from_callable(self.validator),
			accept_handler=self.accept_handler,
			read_only=self.read_only,
			idle_selector_text="",
			focused_selector_text=""
		)
		self.explanation_control = Interactable(text=lambda: self.explanation, style="class:editable.hint")

		return HSplit([
			self.input_control,
			self.explanation_control
		])

	def on_text_changed(self, buffer: Buffer) -> None:
		if self.on_input:
			self.on_input(self, buffer.text)

	def validator(self, text: str) -> bool:
		if self.on_validate:
			result = self.on_validate(self, text)
			if result is not None:
				return result
		return True

	def accept_handler(self, buffer: Buffer) -> bool:
		accepted = True
		if self.on_accept:
			accepted = self.on_accept(self, buffer.text) is not False
		if accepted is False:
			self.application.output.bell()
			return False
		has_text = buffer.text and len(buffer.text) > 0
		self.complete(result=buffer.text if has_text or not self.use_hint_as_fallback or not self.hint else self.hint)
		return True

class Confirm(Input):
	def __init__(
		self,
		prompt: AnyFormattedText = "Are you absolutely sure?",
		explanation: AnyFormattedText = None,
		default_value: bool = True,
		yes_or_no: AnyFormattedText = " (Y/n)",
		no_or_yes: AnyFormattedText = " (N/y)",
	):
		Input.__init__(self, prompt=prompt, hint="", explanation=explanation, fallback=default_value)
		self.control_prompt = merge_formatted_text([prompt, yes_or_no if default_value else no_or_yes])
		self.default_value = default_value
		self.read_only = True

	def create_key_bindings(self) -> KeyBindings:
		bindings = super().create_key_bindings()

		@bindings.add("y")
		@bindings.add("Y")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=True)

		@bindings.add("n")
		@bindings.add("N")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=False)

		@bindings.add(Keys.Enter)
		@bindings.add(" ")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=self.default_value)

		return bindings

class Select(Feedback):
	def __init__(
		self,
		prompt: AnyFormattedText = "What do you like?",
		variants: Iterable[AnyFormattedText] = ["Rides", "Guide", "Both"],
		selected_variant: Optional[Union[int, str]] = None,
		default_variant: Optional[Union[int, str]] = None,
		returns_what: bool = False,
		explanation: AnyFormattedText = None,
		choose_hint: Optional[AnyFormattedText] = None,
		on_focus: Optional[Callable[['Select', int, str, Interactable], None]] = None,
		on_accept: Optional[Callable[['Select', int, str, Interactable], Optional[bool]]] = None,
	):
		Feedback.__init__(self, prompt=prompt, fallback=default_variant)
		self.variants = variants
		self.selected_variant = selected_variant
		self.default_variant = default_variant
		self.returns_what = returns_what
		self.explanation = explanation
		self.on_focus = on_focus
		self.on_accept = on_accept
		self.choose_hint = choose_hint
		self.explanation_prompt = lambda: merge_formatted_text((self.prompt, self.choose_hint))
		self.use_space_as_accept = True

	def create_content(self) -> AnyContainer:
		self.choice_variants: Sequence[AnyContainer] = []
		self.focused_interactable = None
		which_offset = 0
		for variant in self.variants:
			if variant is None:
				continue
			control = self.create_choice_content(variant, which_offset)
			if self.default_variant and (variant == self.default_variant or which_offset == self.default_variant):
				self.focused_interactable = control
			self.choice_variants.append(control)
			which_offset += 1
		self.explanation_control = Interactable(text=lambda: self.explanation, style="class:editable.hint")

		return HSplit([
			Interactable(self.explanation_prompt),
			ScrollablePane(
				HSplit(self.choice_variants),
				scroll_offsets=ScrollOffsets(3, 3),
				display_arrows=False,
			),
			self.explanation_control
		])

	def create_choice_content(self, variant: AnyFormattedText, offset: int) -> AnyContainer:
		selected = self.selected_variant is not None and (
			variant == self.selected_variant or offset == self.selected_variant
		)
		return Interactable(
			variant,
			focusable=True,
			show_cursor=False,
			style="class:selection" if selected else "",
			tag=offset
		)

	def create_layout(self) -> Layout:
		return Layout(self.content, self.focused_interactable)

	def create_key_bindings(self) -> KeyBindings:
		bindings = super().create_key_bindings()

		@bindings.add(Keys.Down)
		def _(event: KeyPressEvent) -> None:
			focus_next(event)
			if self.layout.current_control and isinstance(self.layout.current_control, Interactable):
				self.focus_handler(self.layout.current_control)

		@bindings.add(Keys.Up)
		def _(event: KeyPressEvent) -> None:
			focus_previous(event)
			if self.layout.current_control and isinstance(self.layout.current_control, Interactable):
				self.focus_handler(self.layout.current_control)

		@bindings.add(Keys.Enter)
		@bindings.add(" ", filter=Condition(lambda: self.use_space_as_accept))
		def _(_: KeyPressEvent) -> None:
			if self.layout.current_control and isinstance(self.layout.current_control, Interactable):
				self.accept_handler(self.layout.current_control)
			elif self.default_variant is not None:
				for control in self.layout.find_all_controls():
					if not isinstance(control, Interactable):
						continue
					if isinstance(self.default_variant, str) and self.default_variant == to_plain_text(control.interactable_text):
						self.accept_handler(control)
						break
					elif self.default_variant == control.tag:
						self.accept_handler(control)
						break

		return bindings

	def focus_handler(self, control: Interactable) -> None:
		if self.on_focus:
			text = to_plain_text(control.interactable_text)
			value = cast(int, control.tag)
			self.on_focus(self, value, text, control)

	def accept_handler(self, control: Interactable) -> bool:
		text = to_plain_text(control.interactable_text)
		value = cast(int, control.tag)
		accepted = True
		if self.on_accept:
			accepted = self.on_accept(self, value, text, control) is not False
		if accepted is False:
			self.application.output.bell()
			return False
		self.complete(result=text if self.returns_what else value, print_result=text)
		return True

class Checkbox(Select):
	def __init__(
		self,
		prompt: AnyFormattedText = "What do you like?",
		variants: Iterable[AnyFormattedText] = ["Rides", "Guide", "Both"],
		selected_variants: Optional[Iterable[Union[int, str]]] = None,
		default_variant: Optional[Union[int, str]] = None,
		returns_what: bool = False,
		allow_to_choose_nothing: bool = False,
		explanation: AnyFormattedText = None,
		fallback: Optional[Iterable[Union[int, str]]] = None,
		choose_hint: Optional[AnyFormattedText] = [("class:editable.hint", " <Use Space/Y/N to choose>")],
		on_focus: Optional[Callable[['Checkbox', int, str, Selectable], None]] = None,
		on_checked: Optional[Callable[['Checkbox', int, str, bool, Selectable], Optional[bool]]] = None,
		on_accept: Optional[Callable[['Checkbox', List[int], List[str], Selectable], Optional[bool]]] = None,
	):
		Select.__init__(self, prompt=prompt, variants=variants, default_variant=default_variant, returns_what=returns_what, explanation=explanation, choose_hint=choose_hint)
		self.on_focus = on_focus
		self.on_checked = on_checked
		self.on_accept = on_accept
		if fallback is not None:
			self.fallback = fallback
		self.selected_variants = selected_variants
		self.allow_to_choose_nothing = allow_to_choose_nothing
		self.on_focus = on_focus
		self.on_accept = on_accept
		self.use_space_as_accept = False

	def create_choice_content(self, variant: AnyFormattedText, offset: int) -> AnyContainer:
		selected = self.selected_variants is not None and (
			to_plain_text(variant) in self.selected_variants or offset in self.selected_variants
		)
		return Selectable(
			variant,
			focusable=True,
			checked=selected,
			show_cursor=False,
			on_checked=self.on_choice_checked,
			tag=offset
		)

	def on_choice_checked(self, control: Selectable, checked: bool) -> None:
		text = to_plain_text(control.interactable_text)
		value = cast(int, control.tag)
		accepted = True
		if self.on_checked:
			accepted = self.on_checked(self, value, text, checked, control)
		if accepted is False:
			self.application.output.bell()
			control.checked = not control.checked

	def obtain_selection(self) -> Tuple[List[int], List[str]]:
		selection = ([], [])
		for control in self.choice_variants:
			if isinstance(control, Selectable) and control.checked:
				selection[0].append(cast(int, control.tag))
				selection[1].append(to_plain_text(control.interactable_text))
		return selection

	def accept_handler(self, control: Selectable) -> bool:
		selection = self.obtain_selection()
		assert len(selection[0]) == len(selection[1])
		if not self.allow_to_choose_nothing and len(selection[0]) == 0:
			self.application.output.bell()
			return False
		accepted = True
		if self.on_accept:
			accepted = self.on_accept(self, selection[0], selection[1], control) is not False
		if accepted is False:
			self.application.output.bell()
			return False
		self.complete(result=selection[1] if self.returns_what else selection[0], print_result=selection[1])
		return True

class Review:
	on_receive_feedback: Optional[Callable[['Review', str, Feedback, Any], None]]
	on_request_feedback: Optional[Callable[['Review', str, Feedback], bool]]

	def __init__(self, **feedback: Union[Optional[Feedback], Callable[['Review'], Optional[Feedback]]]) -> None:
		self.current_feedback = None
		self.feedback_keys = [entry for entry in feedback]
		self.feedback_callables = {
			entry: feedback[entry] for entry in feedback
		}

	def request_feedback(self) -> Optional[Feedback]:
		if not hasattr(self, "current_offset"):
			raise ValueError("Review#request_feedback: Review.current_offset")
		if hasattr(self, "current_feedback") and self.current_feedback is not None:
			self.current_feedback.inform_if_already_busy()

		self.current_feedback = None
		self.current_key = None
		while self.current_feedback is None:
			self.current_offset += 1
			if len(self.feedback_keys) <= self.current_offset:
				break

			feedback_key = self.feedback_keys[self.current_offset]
			if not feedback_key or not feedback_key in self.feedback_callables:
				continue

			feedback = self.feedback_callables[feedback_key]
			if callable(feedback):
				feedback = feedback(self)
			if feedback is not None:
				self.current_key = feedback_key
			self.current_feedback = feedback

			if self.current_feedback and hasattr(self, "on_request_feedback") and self.on_request_feedback:
				assert self.current_key is not None
				if not self.on_request_feedback(self, self.current_key, self.current_feedback):
					self.current_feedback = None

		return self.current_feedback

	def receive_feedback(self, returns_empty_properties: bool = False) -> Optional[object]:
		if not hasattr(self, "current_feedback") or self.current_feedback is None or \
				not hasattr(self, "current_key") or self.current_key is None:
			raise ValueError("Review#receive_feedback: Review.current_feedback or Review.current_key")
		if not hasattr(self, "results") or self.results is None:
			raise ValueError("Review#receive_feedback: Review.results")
		self.current_feedback.inform_if_already_busy()

		result = self.current_feedback.get_result()
		if result is not None or returns_empty_properties:
			self.results[self.current_key] = result
			if hasattr(self, "on_receive_feedback") and self.on_receive_feedback:
				self.on_receive_feedback(self, self.current_key, self.current_feedback, result)
		return result

	def require_feedback(self, key: str) -> Feedback:
		if hasattr(self, "current_key") and key == self.current_key and self.current_feedback:
			return self.current_feedback
		if key in self.feedback_callables and self.feedback_callables[key]:
			feedback = self.feedback_callables[key]
			if callable(feedback):
				feedback = feedback(self)
			assert feedback is not None
			return feedback
		raise ValueError(f"Feedback {key!r} is not found!")

	def request(self, returns_empty_properties: bool = False) -> Dict[str, Any]:
		assert not self.current_feedback
		self.results = {}
		self.current_offset = -1
		while True:
			feedback = self.request_feedback()
			if not feedback:
				break
			feedback.request()
			self.receive_feedback(returns_empty_properties=returns_empty_properties)
		self.current_feedback = None
		return self.results

	async def request_async(self, returns_empty_properties: bool = False) -> Any:
		assert not self.current_feedback
		self.results = {}
		self.current_offset = -1
		while True:
			feedback = self.request_feedback()
			if not feedback:
				break
			await feedback.request_async()
			self.receive_feedback(returns_empty_properties=returns_empty_properties)
		self.current_feedback = None
		return self.results

	def request_safe(self, prints_abort: bool = True, returns_empty_properties: bool = False) -> Optional[Dict[str, Any]]:
		try:
			return self.request(returns_empty_properties=returns_empty_properties)
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				attention("Abort.")

	async def request_async_safe(self, prints_abort: bool = True, returns_empty_properties: bool = False) -> Optional[Dict[str, Any]]:
		try:
			return await self.request_async(returns_empty_properties=returns_empty_properties)
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				attention("Abort.")
