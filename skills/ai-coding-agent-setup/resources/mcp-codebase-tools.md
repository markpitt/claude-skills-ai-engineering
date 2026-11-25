# MCP Servers for Codebase Navigation

Model Context Protocol (MCP) gives AI agents live, dynamic access to your IDE, codebase, and infrastructure, beyond what static files can provide. This resource covers the key MCP servers for code navigation, semantic search, and developer tooling.

---

## Overview: Why MCP for Codebase Understanding

Static files (AGENTS.md, skills) give agents context about *how the project works*. MCP gives agents tools to *explore the living codebase*: finding usages, navigating call hierarchies, checking diagnostics, and querying databases.

| Without MCP | With MCP |
|-------------|---------|
| Agent reads a file's source to understand it | Agent calls `find_usages("UserService")` |
| Agent guesses at function signatures | Agent calls `get_type_definition` on any symbol |
| Agent misses a compilation error | Agent calls `get_diagnostics` and sees errors directly |
| Agent re-discovers schema from migration files | Agent queries live DB schema via MCP |

**Check VS Code's built-in tools first.** Before reaching for MCP, check whether VS Code Copilot's built-in tools already cover the need: `get_errors`, semantic search and symbol navigation (`find_usages`, `go_to_definition`) are available natively and need no configuration. Add an MCP server only for something they do not do.

---

## Primary MCP Servers

### 1. GitHub MCP Server - Remote Repository Context

The official GitHub MCP server is hosted remotely by GitHub. In VS Code 1.101 or later it authenticates through VS Code's built-in GitHub OAuth, so no token or environment variable is needed. Use it for code that is not checked out locally and for searches across repositories.

**Configuration** (`.vscode/mcp.json`), VS Code 1.101+ with OAuth:

```json
{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

**Configuration with a personal access token**, where OAuth is unavailable. Use `${input:...}` so VS Code prompts for the token and stores it securely:

```json
{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${input:github_mcp_pat}"
      }
    }
  },
  "inputs": [
    {
      "type": "promptString",
      "id": "github_mcp_pat",
      "description": "GitHub Personal Access Token",
      "password": true
    }
  ]
}
```

Do not use `${env:GITHUB_TOKEN}` for the token: it resolves only if the variable was set in the shell that launched VS Code, and an unset variable gives an empty string rather than an error (see the variable reference below).

**Key Tools:**

| Tool | Purpose |
|------|---------|
| `search_code` | Full-text code search across repositories |
| `get_file_contents` | Read a file from a remote repo |
| `list_commits` | View commit history for a branch or file |
| `pull_request_read` | Read PR details, diffs and review comments |
| `list_issues` | Browse open issues |
| `issue_write` | Create or update an issue from within the agent session |
| `create_pull_request` | Open a PR from within the agent session |

Tools are grouped into toolsets (`repos`, `issues`, `pull_requests`, `actions`, `code_security` and others), and the server can run read-only. The toolset list and the flags that select them change between releases: take them from the [server's README](https://github.com/github/github-mcp-server) rather than from a copy.

**Add to AGENTS.md:**

```markdown
## MCP Tools Available

GitHub MCP (remote HTTP, OAuth through VS Code, VS Code 1.101+):
- `GitHub:search_code` - full-text search across repositories
- `GitHub:get_file_contents` - read files from remote repos
- `GitHub:list_issues`, `GitHub:pull_request_read` - issue and PR context

Use GitHub MCP to cross-reference related repos. VS Code's built-in tools cover local code navigation.
```

---

### 2. vscode-mcp-server - VS Code Control and File Analysis

Open-source server that turns a local VS Code instance into an MCP server. Useful for file editing, terminal and symbol tools where VS Code's built-in tools are not enough.

**Install:** `npx @vscode/mcp-server`

**Configuration** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "vscode": {
      "type": "stdio",
      "command": "npx",
      "args": ["@vscode/mcp-server"]
    }
  }
}
```

**Key Tools:**

| Tool | Purpose |
|------|---------|
| `get_diagnostics_code` | File or workspace errors/warnings |
| `get_symbol_definition_code` | Type info and docs for a symbol at a line |
| `get_document_symbols_code` | Hierarchical outline of functions/classes |
| `search_symbols_code` | Find symbols by name across workspace |
| `open_file` | Open a file in the editor |
| `run_terminal_command` | Execute a terminal command |

---

### 3. Semantic Search via Vector Store MCP

For natural-language queries over large codebases or documentation, connect a vector store.

#### Option A: Qdrant (self-hosted)

```json
{
  "servers": {
    "qdrant": {
      "type": "stdio",
      "command": "npx",
      "args": ["qdrant-mcp-server"],
      "env": {
        "QDRANT_URL": "http://localhost:6333",
        "COLLECTION_NAME": "codebase"
      }
    }
  }
}
```

**Workflow:**
1. Index codebase: `python scripts/index-codebase.py --collection codebase`
2. Query: agent calls `search("How does auth work?")` → returns relevant code chunks

#### Option B: Azure AI Search (cloud)

```json
{
  "servers": {
    "azure-search": {
      "type": "stdio",
      "command": "npx",
      "args": ["azure-ai-search-mcp"],
      "env": {
        "AZURE_SEARCH_ENDPOINT": "${input:azure_search_endpoint}",
        "AZURE_SEARCH_API_KEY": "${input:azure_search_key}",
        "INDEX_NAME": "codebase-index"
      }
    }
  }
}
```

---

### 4. Database MCP Server - Live Schema Access

Prevent agents from guessing at database schemas by giving them direct query access.

**Configuration example (PostgreSQL):**

```json
{
  "servers": {
    "postgres": {
      "type": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/server-postgres"],
      "env": {
        "DATABASE_URL": "${input:database_url}"
      }
    }
  }
}
```

Agents can call:
- `list_tables` - enumerate all tables
- `describe_table` - columns, types, constraints for a table
- `query` - run a SELECT query (read-only by default)

**Security note:** Use a read-only database user for the MCP server connection. Never point MCP at a production database with write credentials.

---

## Minimal mcp.json Template

Place this at `.vscode/mcp.json` in your project root. Start minimal and add servers only as needed.

```json
{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

Add other servers (vscode, postgres, qdrant) only for a specific need that VS Code's built-in tools do not cover.

---

## VS Code Variable Reference for mcp.json

| Variable | Valid? | Use For |
|----------|--------|---------|
| `${workspaceFolder}` | ✅ | Paths relative to workspace root |
| `${userHome}` | ✅ | User home directory |
| `${input:my-id}` | ✅ | Secrets and credentials: VS Code prompts and stores them securely |
| `${env:VAR_NAME}` | ⚠️ | Only if the variable is set in the shell that launched VS Code; empty if unset |

Prefer `${input:...}` over `${env:...}` for credentials.

---

## Tool Selection Guide

When should agents use which tool?

| Question | Preferred Tool |
|----------|---------------|
| "Where is X defined?" | VS Code built-in `go_to_definition` |
| "Who uses X?" | VS Code built-in `find_usages` |
| "Are there compilation errors?" | VS Code built-in `get_errors` |
| "Find all files using a pattern" | VS Code built-in semantic search, or vscode `search_symbols_code` |
| "What's the DB schema for table X?" | DB MCP `describe_table` |
| "How does the auth flow work?" (concept) | Semantic search MCP `search` |
| "Find code in another repo" | GitHub MCP `search_code` |
| "Read a file from a remote repo" | GitHub MCP `get_file_contents` |

Document this guide in AGENTS.md, with fully qualified `Server:tool` names, so agents know which tool to reach for.

---

## Troubleshooting MCP Configuration

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Server not found in agent session | mcp.json missing or malformed JSON | Verify `.vscode/mcp.json` parses; reload the VS Code window |
| Tool call returns "not connected" | MCP server process not running | Check the MCP server logs in the Output panel |
| GitHub MCP auth failure | Not signed in to GitHub in VS Code | Sign in through the Accounts menu in VS Code |
| `${env:GITHUB_TOKEN}` passes an empty string | Variable not set in the shell that launched VS Code | Switch to `${input:github_mcp_pat}` |
| DB query fails with permission denied | DB user lacks permissions | Use a dedicated read-only DB user for MCP |
