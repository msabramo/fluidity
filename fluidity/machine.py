import re
import inspect
from fluidity.backwardscompat import callable

# metaclass implementation idea from
# http://blog.ianbicking.org/more-on-python-metaprogramming-comment-14.html
_transition_gatherer = []

def transition(event, from_, to, action=None, guard=None):
    _transition_gatherer.append([event, from_, to, action, guard])

_state_gatherer = []

def state(name, enter=None, exit=None):
    _state_gatherer.append([name, enter, exit])


class MetaStateMachine(type):

    def __new__(cls, name, bases, dictionary):
        global _transition_gatherer, _state_gatherer
        Machine = super(MetaStateMachine, cls).__new__(cls, name, bases, dictionary)
        Machine._class_transitions = []
        Machine._class_states = {}
        for i in _transition_gatherer:
            Machine._add_class_transition(*i)
        for s in _state_gatherer:
            Machine._add_class_state(*s)
        _transition_gatherer = []
        _state_gatherer = []
        return Machine


StateMachineBase = MetaStateMachine('StateMachineBase', (object, ), {})


class StateMachine(StateMachineBase):

    def __init__(self):
        self.__class__._validate_machine_definitions()
        if callable(self.initial_state):
            self.initial_state = self.initial_state()
        self.current_state = self.initial_state
        self._handle_state_action(self.initial_state, 'enter')
        self._create_state_getters()

    def __new__(cls, *args, **kwargs):
        obj = super(StateMachine, cls).__new__(cls)
        obj._states = {}
        obj._transitions = []
        return obj

    @classmethod
    def _validate_machine_definitions(cls):
        if not getattr(cls, '_class_states', None) or len(cls._class_states) < 2:
            raise InvalidConfiguration('There must be at least two states')
        if not getattr(cls, 'initial_state', None):
            raise InvalidConfiguration('There must exist an initial state')

    @classmethod
    def _add_class_state(cls, name, enter, exit):
        cls._class_states[name] = _State(name, enter, exit)

    def add_state(self, name, enter=None, exit=None):
        self._states[name] = _State(name, enter, exit)
        self._states[name].create_getter_for(self)

    def _state_objects(self):
        return list(self.__class__._class_states.values()) + list(self._states.values())

    def states(self):
        return [s.name for s in self._state_objects()]

    @classmethod
    def _add_class_transition(cls, event, from_, to, action, guard):
#        cls._class_transitions.append(_Transition(event, from_, to, action, guard))
#        this_event = cls._generate_event(event)
#        setattr(cls, this_event.__name__, this_event)
        transition = _Transition(event, from_, to, action, guard)
        cls._class_transitions.append(transition)
        transition.generate_event_for(cls)

    def add_transition(self, event, from_, to, action=None, guard=None):
        transition = _Transition(event, from_, to, action, guard)
        self._transitions.append(transition)
        transition.generate_event_for(self)

    def _process_transitions(self, event_name, *args, **kwargs):
        transitions = self._transitions_by_name(event_name)
        transitions = self._ensure_from_validity(transitions)
        this_transition = self._check_guards(transitions)
        self._run_transition(this_transition, *args, **kwargs)

    def _create_state_getters(self):
        for state in self._state_objects():
            state.create_getter_for(self)

    def _transitions_by_name(self, name):
        return filter(lambda transition: transition.event == name,
            self.__class__._class_transitions + self._transitions)

    def _ensure_from_validity(self, transitions):
        valid_transitions = filter(
          lambda transition: transition.is_valid_from(self.current_state),
          transitions)
        if len(valid_transitions) == 0:
            raise InvalidTransition("Cannot change from %s to %s" % (
                self.current_state, transitions[-1].to))
        return valid_transitions

    def _check_guards(self, transitions):
        allowed_transitions = []
        for transition in transitions:
            if self._check_guard(transition.guard):
                allowed_transitions.append(transition)
        if len(allowed_transitions) == 0:
            raise GuardNotSatisfied("Guard is not satisfied for this transition")
        elif len(allowed_transitions) > 1:
            raise ForkedTransition("More than one transition was allowed for this event")
        return allowed_transitions[0]

    def _run_transition(self, transition, *args, **kwargs):
        self._handle_state_action(self.current_state, 'exit')
        self.current_state = transition.to
        self._handle_state_action(transition.to, 'enter')
        self._handle_action(transition.action, *args, **kwargs)

    def _handle_state_action(self, state, kind):
        try:
            action = getattr(self._class_states[state], kind)
        except KeyError:
            action = getattr(self._states[state], kind)
        self._run_action_or_list(action)

    def _handle_action(self, action, *args, **kwargs):
        self._run_action_or_list(action, *args, **kwargs)

    def _run_action_or_list(self, action_param, *args, **kwargs):
        if not action_param:
            return
        action_items = _listize(action_param)
        for action_item in action_items:
            self._run_action(action_item, *args, **kwargs)

    def _run_action(self, action, *args, **kwargs):
        if callable(action):
            self._try_to_run_with_args(action, self, *args, **kwargs)
        else:
            self._try_to_run_with_args(getattr(self, action), *args, **kwargs)

    def _try_to_run_with_args(self, action, *args, **kwargs):
        try:
            action(*args, **kwargs)
        except TypeError:
            if len(args) > 0 and args[0] == self:
                action(self)
            else:
                action()

    def _check_guard(self, guard_param):
        if guard_param is None:
            return True
        guard_items = _listize(guard_param)
        result = True
        for guard_item in guard_items:
            result = result and self._evaluate_guard(guard_item)
        return result

    def _evaluate_guard(self, guard):
        if callable(guard):
            return guard(self)
        else:
            guard = getattr(self, guard)
            if callable(guard):
                guard = guard()
            return guard


class _Transition(object):

    def __init__(self, event, from_, to, action, guard):
        self.event = event
        self.from_ = from_
        self.to = to
        self.action = action
        self.guard = guard

    def generate_event_for(self, machine):
        this_event = self._generate_event(self.event)
        if inspect.isclass(machine):
            setattr(machine, self.event, this_event)
        else:
            setattr(machine, self.event,
                this_event.__get__(machine, machine.__class__))

    def _generate_event(self, name):
        def generated_event(machine, *args, **kwargs):
            these_transitions = machine._process_transitions(self.event, *args, **kwargs)
        generated_event.__doc__ = 'event %s' % name
        generated_event.__name__ = name
        return generated_event

    def is_valid_from(self, from_):
        return from_ in _listize(self.from_)


class _State(object):

    def __init__(self, name, enter, exit):
        self.name = name
        self.enter = enter
        self.exit = exit

    def create_getter_for(self, objekt):
        def state_getter(self_object):
            return self_object.current_state == self.name
        setattr(objekt, 'is_%s' % self.name, state_getter.__get__(objekt, objekt.__class__))


class InvalidConfiguration(Exception):
    pass


class InvalidTransition(Exception):
    pass


class GuardNotSatisfied(Exception):
    pass


class ForkedTransition(Exception):
    pass


def _listize(value):
    return type(value) in [list, tuple] and value or [value]

