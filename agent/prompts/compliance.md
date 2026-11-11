# compliance v1
Role prompt. Compliance is a deterministic gate with no model: banned phrases and regex patterns from
config (compliance.*), the platform policy banned_link_regex, and the max word count. Rules live in
config and the policy pack so a platform policy change needs no code. A draft that fails is blocked and
the reason is shown in the UI.
