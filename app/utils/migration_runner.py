import os
import sys
import importlib.util

def run_custom_migrations(app):
    """Run all custom migration scripts in the migrations/ directory."""
    with app.app_context():
        migrations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'migrations')
        if not os.path.exists(migrations_dir):
            return

        # Get all migration scripts starting with numbers
        scripts = [f for f in os.listdir(migrations_dir) if f.endswith('.py') and f[0].isdigit()]
        scripts.sort()

        if not scripts:
            return
            
        app.logger.info(f"Checking {len(scripts)} custom migrations...")
        
        for script in scripts:
            script_path = os.path.join(migrations_dir, script)
            module_name = script[:-3]
            
            # Dynamically load the module
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    # Execute module
                    spec.loader.exec_module(module)
                    if hasattr(module, 'migrate'):
                        app.logger.info(f"Running migration: {script}")
                        # We pass app into migrate if it needs it or just call it since it usually creates its own or uses current context
                        module.migrate()
                except Exception as e:
                    app.logger.error(f"Error running migration {script}: {e}")
