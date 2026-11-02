# Contributing to Siesta

Start with a reproducible problem or a small, testable capability. Explain the
expected behavior, the actual result and the model profile when it matters.
Review transcripts before sharing them: they can contain private project data.

## Development loop

1. Follow the [setup guide](docs/getting-started.md) and create a short-lived branch.
2. Add a meaningful regression test for a behavior change.
3. Make the smallest complete change and run the relevant tests.
4. Run the full [offline suite](docs/testing.md), update affected documentation,
   and explain verification in your pull request.

The Python runtime uses the standard library. Prefer a direct function over a
new framework. Preserve explicit model routing, honest verification verdicts,
resume behavior, recovery evidence and third-party license notices.

Tests use temporary projects and fake model replies. Changes to model prompts
or tool invocation also need a real-model check: report the model, Pi version,
input, observed output and limitations. Do not present a mocked run as live
validation or a model claim as a command you actually executed.

See [AGENTS.md](AGENTS.md) for phase contracts and the
[Definition of Done](.agents/references/definition-of-done.md) for the review bar.
