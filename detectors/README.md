# Optional detector plug-ins

Place Python detector modules in this directory. A module may expose
`register_detectors(registry)` and register one or more deterministic checks:

```python
def register_detectors(registry):
    @registry.register("custom_check")
    def custom_check(context):
        return {"status": "checked", "evidence": {"asset_profile": context.asset_profile}}
```

The page loads these modules at startup. A plug-in failure is recorded in the
inspection result and does not disable the built-in rule detectors.
