"""Manage FRIDAY's installed skills at runtime."""
_manager = None


def bind_manager(manager):
    global _manager
    _manager = manager


def list_skills():
    """List available skills and whether each is enabled."""
    if not _manager:
        return 'Skill manager is not ready.'
    return '\n'.join(
        f"- {x['name']}: {'enabled' if x['enabled'] else 'disabled'} — {x['description']}"
        for x in _manager.catalog()
    )


def enable_skill(name):
    """Enable an installed skill by tool name."""
    try:
        return _manager.enable(name)
    except KeyError:
        return f'Unknown skill: {name}'


def disable_skill(name):
    """Disable a skill by tool name."""
    try:
        return _manager.disable(name)
    except KeyError:
        return f'Unknown skill: {name}'


def register_tools(registry):
    # These management tools are always available.
    bind_manager(getattr(registry, '_skill_manager', None))
    for n, fn in [
        ('list_skills', list_skills),
        ('enable_skill', enable_skill),
        ('disable_skill', disable_skill),
    ]:
        props = {} if n == 'list_skills' else {'name': {'type': 'string'}}
        registry.register_tool(n, fn, {
            'name': n,
            'description': fn.__doc__,
            'parameters': {
                'type': 'object',
                'properties': props,
                'required': [] if not props else ['name'],
            },
        })
