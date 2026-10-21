"""Names for observable command activity; no generated internal reasoning."""

def tool_activity(name, arguments):
    view=arguments.get('view','summary')
    captions={
        'inspect_path': ('Finding the largest files' if view=='largest_files' else 'Finding the largest folder items' if view=='children' else 'Measuring storage use', 'inspecting'),
        'find_paths': ('Searching for files and folders','searching'),
        'disk_space': ('Checking free disk space','inspecting'),
        'system_health': ('Reading memory, CPU load, and disk space','inspecting'),
        'service_status': ('Checking service status','inspecting'),
        'get_local_time': ('Reading the local clock','inspecting'),
        'get_system_status': ('Checking Jarvis services','inspecting'),
        'describe_latest_scene': ('Reading the latest scene analysis','inspecting'),
        'list_recent_analyses': ('Finding recent scene analyses','searching'),
        'get_volume': ('Checking speaker volume','inspecting'),
        'set_volume': ('Adjusting speaker volume','acting'),
        'change_volume': ('Adjusting speaker volume','acting'),
        'set_mute': ('Updating speaker mute','acting'),
        'take_picture': ('Capturing the requested picture','acting'),
    }
    caption,step=captions.get(name,('Running the selected action','acting'))
    target=arguments.get('path',arguments.get('unit',arguments.get('query','')))
    return {'activity_caption':caption,'activity_step':step,'activity_target':str(target)}
