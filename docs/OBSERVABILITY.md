# Named CI observations and evidence graphs

Observation adapters are read-only. They cannot trigger jobs, fetch arbitrary endpoints, send messages or publish records. Source registration is read from the authenticated code repository's upstream main commit; a proposed local registry cannot activate a connector.

A reviewed `.brain-bridge/connectors.json` can contain synthetic-shaped entries like:

```json
{"schema_version":1,"connectors":[
  {"name":"public-ci-example","provider":"github_actions","repository":"example/code","repository_id":"123"},
  {"name":"gitlab-example","provider":"gitlab","host":"gitlab.example","project_id":"55"},
  {"name":"jenkins-example","provider":"jenkins","job_url":"https://ci.example/job/project/","username_env":"BRAIN_BRIDGE_JENKINS_USER","token_env":"BRAIN_BRIDGE_JENKINS_TOKEN"}
]}
```

These are documentation values, not active sources or credentials. GitHub uses existing `gh` authentication; GitLab uses the existing authenticated `glab` host; Jenkins uses explicitly named environment credentials over HTTPS. Cross-host redirects and credential-bearing URLs are rejected. Provider failures do not echo credential headers or response bodies.

```sh
python3 -m brain_bridge observe --identity-repo /path/to/code --connector gitlab-example --run-id 9 --pretty
python3 -m brain_bridge graph --identity-repo /path/to/code --repo /path/to/data --format mermaid --pretty
```

Observers verify the registered repository/project and selected run/build identity. Queued or running work is not reported as successful. Native status/result values are preserved; missing results remain unknown. No artifact payload is downloaded. GitLab nested namespace information is retained separately from stable project IDs.

The graph command reauthorizes managed source access and derives relationships only from explicit coverage, supersedes and provenance fields. Library callers can attach an authoritative task snapshot; task states are never inferred from prose or next_steps. Missing prerequisites remain unresolved and cycles are reported. JSON is deterministic; DOT/Mermaid are returned as a content field in the same versioned JSON response. Labels are escaped, not accepted as diagram commands or HTML. No graph is uploaded automatically.

Provider references: [GitLab pipelines API](https://docs.gitlab.com/api/pipelines/), [authenticated glab API transport](https://docs.gitlab.com/cli/api/), [Jenkins remote API](https://www.jenkins.io/doc/book/using/remote-access-api/).

The selected-object GitHub connector additionally collects issues, PRs, commits and workflow runs, projects explicit Brain/task evidence, and rechecks registration before returning results. See [GitHub connector](GITHUB-CONNECTOR.md). This does not activate any source or infer task completion.
