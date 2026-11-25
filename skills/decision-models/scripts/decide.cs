#!/usr/bin/env -S dotnet run --file
// SPDX-License-Identifier: Apache-2.0
// decide: ask a System One decision model (text state in, probabilities out) yes/no, choice and
// score questions, with recipes for CI triage, commits, routing and review comments. Run it through
// the `decide` shim beside this file. The SystemOne region at the bottom has no dependency on the
// CLI and can be copied into an app as it is: BCL only, no reflection-based JSON, so it also works
// under Native AOT.
#:property Nullable=enable
#:property TreatWarningsAsErrors=true
#:property InvariantGlobalization=true

using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using SystemOne;

return await Cli.RunAsync(args);

static class ExitCodes
{
    public const int Yes = 0;
    public const int No = 1;
    public const int Usage = 2;
    public const int Unsure = 3;
    public const int Api = 4;
}

sealed class UsageException(string message) : Exception(message);

static class Cli
{
    const string Help = """
        Usage: decide [global options] COMMAND [options]

        Ask a System One decision model questions about a text or JSON state. Answers are
        probabilities, never prose. Free model by default; one request per command.

        Commands:
          ask            one ad hoc question, or a questions file
          ci-triage      classify a failed CI log (billing, flaky, restore, code defect ...)
          commit-check   check staged changes or a commit: type, subject, changelog, public API
          route          pick which target (repository, team, queue) an issue or idea belongs to
          review         classify a pull request review comment
          label          record what really happened for a logged decision
          calibrate      Brier score and accuracy per question, from labelled decisions
          log            show recent logged decisions

        Global options:
          --model ID       default inception/mercury-decide:free (or $DECIDE_MODEL)
          --served-as ID   the model name the reply must carry, when a gateway reports its
                           own name for --model (or $DECIDE_SERVED_MODEL); default --model
          --dry-run        print the request body, send nothing
          --replay FILE    read the response from FILE instead of calling the API
          --no-log         do not append to the decision log
          --json           print the raw answers object
          --timeout SEC    request timeout, default 30
          -h, --help       this help; COMMAND --help for command help

        Exit codes: 0 yes/confident, 1 no, 2 usage, 3 unsure, 4 API or network failure, or
        the reply was served by another model than --served-as (exact match).
        Auth: set OPENROUTER_API_KEY, unless a proxy injects the key for openrouter.ai.
        Log: $DECIDE_LOG or ${XDG_STATE_HOME:-~/.local/state}/decide/decide.jsonl
        """;

    public static async Task<int> RunAsync(string[] argv)
    {
        // The shim runs dotnet from this file's directory; relative paths mean the caller's.
        if (Environment.GetEnvironmentVariable("DECIDE_CALLER_DIR") is { Length: > 0 } caller && Directory.Exists(caller))
        {
            Directory.SetCurrentDirectory(caller);
        }
        var args = new Args(argv);
        try
        {
            var global = GlobalOptions.Parse(args);
            var command = args.NextPositional();
            if (command is null || command is "help")
            {
                Console.WriteLine(Help);
                return command is null && !global.Help ? ExitCodes.Usage : 0;
            }
            if (global.Help)
            {
                args.PushHelp();
            }
            return command switch
            {
                "ask" => await AskCommand.RunAsync(args, global),
                "ci-triage" => await CiTriageCommand.RunAsync(args, global),
                "commit-check" => await CommitCheckCommand.RunAsync(args, global),
                "route" => await RouteCommand.RunAsync(args, global),
                "review" => await ReviewCommand.RunAsync(args, global),
                "label" => LogCommands.Label(args),
                "calibrate" => LogCommands.Calibrate(args),
                "log" => LogCommands.Show(args),
                _ => throw new UsageException($"unknown command '{command}'"),
            };
        }
        catch (UsageException ex)
        {
            Console.Error.WriteLine($"decide: {ex.Message}");
            Console.Error.WriteLine("Try 'decide --help'.");
            return ExitCodes.Usage;
        }
        catch (SystemOneException ex)
        {
            Console.Error.WriteLine($"decide: {ex.Message}");
            return ExitCodes.Api;
        }
    }
}

/// <summary>Minimal argument cursor: flags may appear anywhere, values follow their flag.</summary>
sealed class Args(string[] argv)
{
    readonly List<string> _items = [.. argv];

    public bool Flag(params string[] names)
    {
        var index = _items.FindIndex(names.Contains);
        if (index < 0)
        {
            return false;
        }
        _items.RemoveAt(index);
        return true;
    }

    public string? Value(params string[] names)
    {
        var index = _items.FindIndex(names.Contains);
        if (index < 0)
        {
            return null;
        }
        if (index + 1 >= _items.Count)
        {
            throw new UsageException($"{_items[index]} needs a value");
        }
        var value = _items[index + 1];
        _items.RemoveRange(index, 2);
        return value;
    }

    public List<string> Values(params string[] names)
    {
        var values = new List<string>();
        while (Value(names) is { } value)
        {
            values.Add(value);
        }
        return values;
    }

    public string? NextPositional()
    {
        var index = _items.FindIndex(item => item == "-" || !item.StartsWith('-'));
        if (index < 0)
        {
            return null;
        }
        var value = _items[index];
        _items.RemoveAt(index);
        return value;
    }

    public void PushHelp() => _items.Add("--help");

    public void EnsureEmpty()
    {
        if (_items.Count > 0)
        {
            throw new UsageException($"unexpected argument '{_items[0]}'");
        }
    }
}

sealed record GlobalOptions(
    string Model,
    string ServedAs,
    bool DryRun,
    string? Replay,
    bool NoLog,
    bool Json,
    TimeSpan Timeout,
    bool Help)
{
    public static GlobalOptions Parse(Args args)
    {
        var timeout = args.Value("--timeout");
        var model = args.Value("--model") ?? Environment.GetEnvironmentVariable("DECIDE_MODEL") ?? SystemOneClient.DefaultModel;
        return new GlobalOptions(
            model,
            args.Value("--served-as") ?? (Environment.GetEnvironmentVariable("DECIDE_SERVED_MODEL") is { Length: > 0 } served ? served : model),
            args.Flag("--dry-run"),
            args.Value("--replay"),
            args.Flag("--no-log"),
            args.Flag("--json"),
            TimeSpan.FromSeconds(timeout is null ? 30 : Input.Positive(timeout, "--timeout")),
            args.Flag("-h", "--help"));
    }
}

static class Input
{
    public static double Positive(string text, string flag) =>
        double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && value > 0
            ? value
            : throw new UsageException($"{flag} must be a positive number");

    public static double Probability(string text, string flag) =>
        double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && value is >= 0 and <= 1
            ? value
            : throw new UsageException($"{flag} must be between 0 and 1");

    /// <summary>TEXT, @FILE or - for stdin.</summary>
    public static string Text(string spec)
    {
        if (spec == "-")
        {
            return Console.In.ReadToEnd();
        }
        if (spec.StartsWith('@'))
        {
            var path = spec[1..];
            return File.Exists(path) ? File.ReadAllText(path) : throw new UsageException($"no such file: {path}");
        }
        return spec;
    }

    /// <summary>A JSON object or array stays structured; anything else is sent as a string.</summary>
    public static JsonNode State(string text)
    {
        var trimmed = text.TrimStart();
        if (trimmed.StartsWith('{') || trimmed.StartsWith('['))
        {
            try
            {
                return JsonNode.Parse(text) ?? JsonValue.Create(text);
            }
            catch (JsonException)
            {
            }
        }
        return JsonValue.Create(text);
    }
}

/// <summary>Sends one request (or prints / replays it), logs it, and hands back the answers.</summary>
static class Runner
{
    public static async Task<IReadOnlyDictionary<string, Answer>?> DecideAsync(
        GlobalOptions global, string recipe, JsonNode state, IReadOnlyDictionary<string, Question> questions)
    {
        var request = new DecisionRequest(global.Model, state, questions);
        if (global.DryRun)
        {
            Console.WriteLine(request.ToJson().ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return null;
        }

        var stopwatch = Stopwatch.StartNew();
        DecisionResponse response;
        if (global.Replay is { } replay)
        {
            if (!File.Exists(replay))
            {
                throw new UsageException($"no such file: {replay}");
            }
            response = DecisionResponse.Parse(File.ReadAllText(replay));
        }
        else
        {
            using var client = SystemOneClient.FromEnvironment(global.Timeout);
            response = await client.DecideAsync(request);
        }
        stopwatch.Stop();

        if (!global.NoLog && global.Replay is null)
        {
            var id = DecisionLog.Append(recipe, request, response, stopwatch.Elapsed);
            Console.Error.WriteLine($"decide: logged as {id}");
        }
        // A gateway fallback, a client retry or a re-pointed alias returns a clean answer from a
        // model nobody tested. Refuse it rather than count it; exit 4 means "no model reachable".
        // Exact by design: a gateway that renames the model needs an explicit --served-as, not a guess.
        if (response.Model.Length == 0)
        {
            Console.Error.WriteLine($"decide: the reply did not say which model served it; asked for {request.Model}, not verified");
        }
        else if (!string.Equals(response.Model, global.ServedAs, StringComparison.Ordinal))
        {
            var expected = global.ServedAs == request.Model ? "" : $" (expected {global.ServedAs})";
            throw new SystemOneException(
                $"asked for {request.Model}{expected} but the reply was served by {response.Model}; answer not used (silent fallback?)");
        }
        if (global.Json)
        {
            Console.WriteLine(response.RawAnswers.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        }
        return response.Answers;
    }

    public static string Describe(Answer answer) => answer switch
    {
        YesNoAnswer yes => $"{(yes.Probability >= 0.5 ? "yes" : "no")}  p(yes)={yes.Probability:0.000}",
        ChoiceAnswer choice => $"{choice.Choice}  ({string.Join(", ", choice.Probabilities.OrderByDescending(p => p.Value).Select(p => $"{p.Key} {p.Value:0.000}"))})",
        ScoreAnswer score => $"{score.Score:0.000}  most likely: {score.Legend[score.Probabilities.MaxBy(p => p.Value).Key]}",
        _ => answer.ToString() ?? "",
    };
}

static class AskCommand
{
    const string Help = """
        Usage: decide ask --state STATE (--yes-no Q | --choice Q --option KEY=DESC... |
                          --score Q --anchor LOW ... --anchor HIGH | --questions FILE) [options]

        STATE is TEXT, @FILE or - (stdin). JSON objects are sent structured.

          --yes-no Q          probability that the answer is yes
          --choice Q          pick one --option KEY=DESCRIPTION (two or more)
          --score Q           position on the --anchor scale, lowest first (two or more)
          --questions FILE    a JSON object of named questions in the API's own shape
          --name NAME         question name in the log, default "q"
          --yes P             yes/no exit 0 at or above P (default 0.8)
          --no P              yes/no exit 1 at or below P (default 0.2); between is exit 3
          --min-confidence P  choice/score exit 3 below P (default 0.6)

        Examples:
          decide ask --state @notes.md --yes-no "Is this ready to publish?"
          git diff | decide ask --state - --choice "Which area?" --option ui="user interface" --option data="data access"
        """;

    public static async Task<int> RunAsync(Args args, GlobalOptions global)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine(Help);
            return 0;
        }
        var stateSpec = args.Value("--state") ?? throw new UsageException("ask needs --state");
        var name = args.Value("--name") ?? "q";
        var yesAt = Input.Probability(args.Value("--yes") ?? "0.8", "--yes");
        var noAt = Input.Probability(args.Value("--no") ?? "0.2", "--no");
        var minConfidence = Input.Probability(args.Value("--min-confidence") ?? "0.6", "--min-confidence");
        if (noAt > yesAt)
        {
            throw new UsageException("--no must not be above --yes");
        }

        var questions = BuildQuestions(args, name);
        args.EnsureEmpty();
        var answers = await Runner.DecideAsync(global, "ask", Input.State(Input.Text(stateSpec)), questions);
        if (answers is null)
        {
            return 0;
        }

        var exit = ExitCodes.Yes;
        foreach (var (key, answer) in answers)
        {
            if (!global.Json)
            {
                Console.WriteLine(answers.Count == 1 ? Runner.Describe(answer) : $"{key}: {Runner.Describe(answer)}");
            }
            var code = answer switch
            {
                YesNoAnswer yes when yes.Probability >= yesAt => ExitCodes.Yes,
                YesNoAnswer yes when yes.Probability <= noAt => ExitCodes.No,
                YesNoAnswer => ExitCodes.Unsure,
                ChoiceAnswer choice when choice.Confidence < minConfidence => ExitCodes.Unsure,
                ScoreAnswer score when score.Confidence < minConfidence => ExitCodes.Unsure,
                _ => ExitCodes.Yes,
            };
            exit = Math.Max(exit, code);
        }
        return exit;
    }

    static Dictionary<string, Question> BuildQuestions(Args args, string name)
    {
        var yesNo = args.Value("--yes-no");
        var choice = args.Value("--choice");
        var score = args.Value("--score");
        var file = args.Value("--questions");
        var options = args.Values("--option");
        var anchors = args.Values("--anchor");
        var given = new[] { yesNo, choice, score, file }.Count(v => v is not null);
        if (given != 1)
        {
            throw new UsageException("give exactly one of --yes-no, --choice, --score or --questions");
        }
        if (file is not null)
        {
            return Question.ParseMany(Input.Text("@" + file));
        }
        if (yesNo is not null)
        {
            return new() { [name] = new YesNoQuestion(yesNo) };
        }
        if (choice is not null)
        {
            if (options.Count < 2)
            {
                throw new UsageException("--choice needs at least two --option KEY=DESCRIPTION");
            }
            var parsed = new Dictionary<string, string>();
            foreach (var option in options)
            {
                var split = option.IndexOf('=');
                if (split <= 0)
                {
                    throw new UsageException($"--option '{option}' is not KEY=DESCRIPTION");
                }
                parsed[option[..split]] = option[(split + 1)..];
            }
            return new() { [name] = new ChoiceQuestion(choice, parsed) };
        }
        if (anchors.Count < 2)
        {
            throw new UsageException("--score needs at least two --anchor values, lowest first");
        }
        return new() { [name] = new ScoreQuestion(score!, anchors) };
    }
}

static class CiTriageCommand
{
    const string Help = """
        Usage: decide ci-triage (--log FILE | - | --run ID --repo OWNER/REPO) [--tail N]

        Classifies why a CI job failed and whether a plain re-run is likely to pass. --run fetches
        the failed steps' log with `gh run view --log-failed`. The tail of the log (default 120
        lines) plus up to 40 earlier error lines are sent.

        Labels: code-defect, flaky-test, dependency-restore, quality-gate, infrastructure,
        actions-billing, timeout. Exit 3 when the top label is below 0.6.
        """;

    public static readonly Dictionary<string, string> Labels = new()
    {
        ["code-defect"] = "a compile error, warning treated as error or a test assertion that the change under test caused",
        ["flaky-test"] = "a test that fails intermittently from timing, ordering, races or an environment quirk, with no code cause in the log",
        ["dependency-restore"] = "package restore or install failure, lock file mismatch, or a missing package version on the feed or registry",
        ["quality-gate"] = "a gate failed rather than a build: coverage threshold, formatter, linter, type checker or another policy check",
        ["infrastructure"] = "runner, network, DNS, container, package mirror or third-party service problem unrelated to the code",
        ["actions-billing"] = "the job never started or was refused because GitHub Actions credit, spending limit or payment ran out",
        ["timeout"] = "the job or a step hit its time limit or was cancelled",
    };

    public static async Task<int> RunAsync(Args args, GlobalOptions global)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine(Help);
            return 0;
        }
        var logPath = args.Value("--log");
        var run = args.Value("--run");
        var repo = args.Value("--repo", "-R");
        var tail = (int)Input.Positive(args.Value("--tail") ?? "120", "--tail");
        var stdin = args.NextPositional();
        args.EnsureEmpty();

        string log;
        if (run is not null)
        {
            if (repo is null)
            {
                throw new UsageException("--run needs --repo OWNER/REPO");
            }
            log = Shell.Run("gh", ["run", "view", run, "--repo", repo, "--log-failed"], allowFailure: true);
        }
        else if (logPath is not null)
        {
            log = Input.Text("@" + logPath);
        }
        else if (stdin == "-")
        {
            log = Console.In.ReadToEnd();
        }
        else
        {
            throw new UsageException("give --log FILE, - for stdin, or --run ID --repo OWNER/REPO");
        }

        var state = new JsonObject
        {
            ["repository"] = repo,
            ["log_excerpt"] = Excerpt(log, tail),
            ["log_was_empty"] = string.IsNullOrWhiteSpace(log),
        };
        var questions = new Dictionary<string, Question>
        {
            ["cause"] = new ChoiceQuestion("Why did this CI job fail?", Labels),
            ["rerun_passes"] = new YesNoQuestion("Would re-running this job with no code change most likely pass?"),
        };
        var answers = await Runner.DecideAsync(global, "ci-triage", state, questions);
        if (answers is null)
        {
            return 0;
        }
        var cause = (ChoiceAnswer)answers["cause"];
        var rerun = (YesNoAnswer)answers["rerun_passes"];
        if (!global.Json)
        {
            Console.WriteLine($"cause         {Runner.Describe(cause)}");
            Console.WriteLine($"re-run passes {Runner.Describe(rerun)}");
            Console.WriteLine($"next          {NextStep(cause.Choice)}");
        }
        return cause.Confidence < 0.6 ? ExitCodes.Unsure : ExitCodes.Yes;
    }

    static string NextStep(string label) => label switch
    {
        "actions-billing" => "report that Actions billing or the spending limit stopped the run; nothing to fix in code",
        "flaky-test" => "re-run once; a second failure is real, so root-cause it",
        "infrastructure" => "re-run once; if it repeats, check the service status",
        "timeout" => "look for a hang before raising the limit",
        "dependency-restore" => "regenerate lock files with the package manager, never by hand",
        "quality-gate" => "run the gate locally and fix the work, not the gate",
        _ => "read the first error and fix the code",
    };

    /// <summary>Earlier error lines (often the real cause) followed by the tail of the log.</summary>
    public static string Excerpt(string log, int tail)
    {
        var lines = log.Split('\n');
        var tailStart = Math.Max(0, lines.Length - tail);
        var errors = lines[..tailStart]
            .Where(l => l.Contains("error", StringComparison.OrdinalIgnoreCase) || l.Contains("fail", StringComparison.OrdinalIgnoreCase))
            .TakeLast(40);
        var text = string.Join('\n', errors.Concat(["..."]).Concat(lines[tailStart..]));
        return text.Length > 12_000 ? text[^12_000..] : text;
    }
}

static class CommitCheckCommand
{
    const string Help = """
        Usage: decide commit-check [-C DIR] [--rev REV] [--message SUBJECT] [--questions FILE] [--strict]

        Checks the staged diff (or commit REV): Conventional Commits type, subject accuracy,
        changelog-worthy behaviour change, and public API change needing docs. Advisory: prints
        flags, exit 0. --strict exits 1 when any flag fires, for use in a commit-msg hook.

          --questions FILE  extra project-specific questions in the API's shape, asked in the
                            same request. Word them so that yes, or a high score, means a
                            problem: a yes/no at or above 0.7 or a score at or above 0.5 is
                            flagged. Choice answers are printed only.
        """;

    static readonly Dictionary<string, string> Types = new()
    {
        ["feat"] = "adds a capability or option users or app authors can use",
        ["fix"] = "corrects wrong behaviour or a crash",
        ["refactor"] = "restructures code with no behaviour change",
        ["perf"] = "makes existing behaviour faster or use less memory",
        ["test"] = "adds or changes tests only",
        ["docs"] = "documentation, comments or guides only",
        ["build"] = "project files, packages, lock files or SDK pins",
        ["ci"] = "GitHub Actions workflows or CI scripts",
        ["chore"] = "maintenance that fits nothing else, such as release bumps",
    };

    public static async Task<int> RunAsync(Args args, GlobalOptions global)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine(Help);
            return 0;
        }
        var dir = args.Value("-C") ?? ".";
        var rev = args.Value("--rev");
        var message = args.Value("--message", "-m");
        var strict = args.Flag("--strict");
        var extraFile = args.Value("--questions");
        args.EnsureEmpty();
        var extra = extraFile is null ? [] : Question.ParseMany(Input.Text("@" + extraFile));

        string[] range = rev is null ? ["--cached"] : [$"{rev}^!"];
        var files = Shell.Run("git", ["-C", dir, "diff", "--name-only", .. range]).Split('\n', StringSplitOptions.RemoveEmptyEntries);
        if (files.Length == 0)
        {
            throw new UsageException(rev is null ? "nothing is staged" : $"{rev} changes no files");
        }
        var stat = Shell.Run("git", ["-C", dir, "diff", "--stat", .. range]);
        var diff = Shell.Run("git", ["-C", dir, "diff", "--unified=2", .. range]);
        message ??= rev is null ? null : Shell.Run("git", ["-C", dir, "log", "-1", "--format=%s", rev]).Trim();

        var state = new JsonObject
        {
            ["commit_subject"] = message,
            ["files"] = new JsonArray([.. files.Select(f => (JsonNode?)JsonValue.Create(f))]),
            ["stat"] = stat,
            ["diff_excerpt"] = diff.Length > 10_000 ? diff[..10_000] + "\n... (truncated)" : diff,
        };
        var questions = new Dictionary<string, Question>
        {
            ["type"] = new ChoiceQuestion("Which Conventional Commits type fits this diff best?", Types),
            ["user_visible"] = new YesNoQuestion("Does this diff change behaviour that a user or a downstream consumer would notice, so it belongs in the changelog?"),
            ["public_api"] = new YesNoQuestion("Does this diff add, remove or change a public type, function or member signature?"),
        };
        foreach (var (name, question) in extra)
        {
            if (!questions.TryAdd(name, question))
            {
                throw new UsageException($"--questions: '{name}' clashes with a built-in question");
            }
        }
        if (message is not null)
        {
            questions["subject_matches"] = new YesNoQuestion("Does the commit subject accurately describe what the diff does?");
        }

        var answers = await Runner.DecideAsync(global, "commit-check", state, questions);
        if (answers is null)
        {
            return 0;
        }

        var flags = new List<string>();
        var type = (ChoiceAnswer)answers["type"];
        var userVisible = ((YesNoAnswer)answers["user_visible"]).Probability;
        var publicApi = ((YesNoAnswer)answers["public_api"]).Probability;
        var declaredType = message?.Split(':', 2)[0].Split('(')[0].TrimEnd('!');
        if (declaredType is not null && Types.ContainsKey(declaredType) && type.Confidence >= 0.6 && declaredType != type.Choice)
        {
            flags.Add($"subject says '{declaredType}' but the diff reads as '{type.Choice}'");
        }
        if (answers.TryGetValue("subject_matches", out var subject) && ((YesNoAnswer)subject).Probability < 0.3)
        {
            flags.Add("the subject may not describe the diff");
        }
        if (userVisible >= 0.7 && !files.Any(f => f.EndsWith("CHANGELOG.md", StringComparison.OrdinalIgnoreCase)))
        {
            flags.Add("user-visible change with no CHANGELOG.md entry");
        }
        if (publicApi >= 0.7 && !files.Any(f => f.StartsWith("docs/", StringComparison.Ordinal) || f.EndsWith(".md", StringComparison.Ordinal)))
        {
            flags.Add("public API change with no docs change in the same commit");
        }
        foreach (var name in extra.Keys)
        {
            switch (answers.GetValueOrDefault(name))
            {
                case YesNoAnswer yes when yes.Probability >= 0.7:
                    flags.Add($"{name}: p(yes)={yes.Probability:0.000}");
                    break;
                case ScoreAnswer score when score.Score >= 0.5:
                    flags.Add($"{name}: {Runner.Describe(score)}");
                    break;
            }
        }

        if (!global.Json)
        {
            Console.WriteLine($"type           {Runner.Describe(type)}");
            Console.WriteLine($"user visible   p={userVisible:0.000}");
            Console.WriteLine($"public API     p={publicApi:0.000}");
            foreach (var name in extra.Keys)
            {
                if (answers.TryGetValue(name, out var answer))
                {
                    Console.WriteLine($"{name,-14} {Runner.Describe(answer)}");
                }
            }
            if (subject is YesNoAnswer s)
            {
                Console.WriteLine($"subject fits   p={s.Probability:0.000}");
            }
            Console.WriteLine(flags.Count == 0 ? "flags          none" : string.Join('\n', flags.Select(f => $"flag           {f}")));
        }
        return strict && flags.Count > 0 ? ExitCodes.No : ExitCodes.Yes;
    }
}

static class RouteCommand
{
    const string Help = """
        Usage: decide route (--text TEXT|@FILE|-) [--targets FILE]

        Picks which target an issue, bug report or idea belongs to: a repository, a team, a queue.
        Targets come from a JSON object of KEY: DESCRIPTION, from --targets or $DECIDE_TARGETS.
        Describe what belongs in each target, not just its name. Exit 3 when the top target is
        below 0.6, which usually means it spans targets or needs a person.

        Example targets file:
          { "api": "the HTTP API: endpoints, auth, rate limits",
            "web": "the browser front end: pages, styling, client-side state",
            "docs": "user guides and reference documentation" }
        """;

    public static async Task<int> RunAsync(Args args, GlobalOptions global)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine(Help);
            return 0;
        }
        var text = args.Value("--text") ?? throw new UsageException("route needs --text");
        var targetsPath = args.Value("--targets") ?? Environment.GetEnvironmentVariable("DECIDE_TARGETS")
            ?? throw new UsageException("route needs --targets FILE or $DECIDE_TARGETS");
        args.EnsureEmpty();
        var targets = Targets(Input.Text("@" + targetsPath));
        var answers = await Runner.DecideAsync(
            global,
            "route",
            JsonValue.Create(Input.Text(text)),
            new Dictionary<string, Question>
            {
                ["target"] = new ChoiceQuestion("Where should this issue or idea be filed?", targets),
            });
        if (answers is null)
        {
            return 0;
        }
        var target = (ChoiceAnswer)answers["target"];
        if (!global.Json)
        {
            Console.WriteLine(Runner.Describe(target));
        }
        return target.Confidence < 0.6 ? ExitCodes.Unsure : ExitCodes.Yes;
    }

    static Dictionary<string, string> Targets(string json)
    {
        JsonObject? root;
        try
        {
            root = JsonNode.Parse(json) as JsonObject;
        }
        catch (JsonException ex)
        {
            throw new UsageException($"targets file is not JSON: {ex.Message}");
        }
        var targets = root?.ToDictionary(p => p.Key, p => p.Value is JsonValue v && v.TryGetValue<string>(out var d) ? d : "")
            ?? throw new UsageException("targets file must be a JSON object of KEY: DESCRIPTION");
        if (targets.Count < 2 || targets.Values.Any(string.IsNullOrWhiteSpace))
        {
            throw new UsageException("targets file needs at least two targets, each with a description");
        }
        return targets;
    }
}

static class ReviewCommand
{
    const string Help = """
        Usage: decide review (--text TEXT|@FILE|-) [--diff-hunk TEXT|@FILE]

        Classifies a review comment so an agent knows whether it must push a fix, can reply, or
        must ask the author: blocking-bug, security, test-gap, small-change, design, question, nit,
        praise. Also asks whether merging without a code change would be wrong.
        """;

    static readonly Dictionary<string, string> Kinds = new()
    {
        ["blocking-bug"] = "points at a real defect that would ship broken behaviour",
        ["security"] = "points at a security or secret-handling problem",
        ["test-gap"] = "asks for a missing or stronger test",
        ["small-change"] = "asks for a small local change such as a rename or a one-function refactor",
        ["design"] = "questions the approach, API shape or architecture across files",
        ["question"] = "asks why something is the way it is, without asking for a change",
        ["nit"] = "optional style, wording or formatting preference",
        ["praise"] = "approval or thanks with nothing to do",
    };

    public static async Task<int> RunAsync(Args args, GlobalOptions global)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine(Help);
            return 0;
        }
        var text = args.Value("--text") ?? throw new UsageException("review needs --text");
        var hunk = args.Value("--diff-hunk");
        args.EnsureEmpty();
        var state = new JsonObject
        {
            ["comment"] = Input.Text(text),
            ["diff_hunk"] = hunk is null ? null : Input.Text(hunk),
        };
        var answers = await Runner.DecideAsync(global, "review", state, new Dictionary<string, Question>
        {
            ["kind"] = new ChoiceQuestion("What kind of review comment is this?", Kinds),
            ["needs_change"] = new YesNoQuestion("Is the reviewer requiring a code change before merge, rather than offering an optional suggestion or asking a question?"),
        });
        if (answers is null)
        {
            return 0;
        }
        if (!global.Json)
        {
            Console.WriteLine($"kind          {Runner.Describe(answers["kind"])}");
            Console.WriteLine($"needs change  {Runner.Describe(answers["needs_change"])}");
        }
        return ((ChoiceAnswer)answers["kind"]).Confidence < 0.6 ? ExitCodes.Unsure : ExitCodes.Yes;
    }
}

static class Shell
{
    public static string Run(string file, IEnumerable<string> arguments, bool allowFailure = false)
    {
        var start = new ProcessStartInfo(file) { RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in arguments)
        {
            start.ArgumentList.Add(argument);
        }
        using var process = Process.Start(start) ?? throw new UsageException($"could not start {file}");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        if (process.ExitCode != 0 && !allowFailure)
        {
            throw new UsageException($"{file} {string.Join(' ', start.ArgumentList)} failed: {stderr.Result.Trim()}");
        }
        return stdout.Result + (allowFailure ? stderr.Result : "");
    }
}

/// <summary>
/// Append-only JSONL: decide.jsonl holds every decision, decide-labels.jsonl the outcomes recorded
/// afterwards with `decide label`. Kept apart so a label never rewrites history.
/// </summary>
static class DecisionLog
{
    public static string Path =>
        Environment.GetEnvironmentVariable("DECIDE_LOG") is { Length: > 0 } path
            ? path
            : System.IO.Path.Combine(
                Environment.GetEnvironmentVariable("XDG_STATE_HOME") is { Length: > 0 } state
                    ? state
                    : System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "state"),
                "decide",
                "decide.jsonl");

    public static string LabelsPath => System.IO.Path.ChangeExtension(Path, null) + "-labels.jsonl";

    public static string Append(string recipe, DecisionRequest request, DecisionResponse response, TimeSpan elapsed)
    {
        var stateText = request.State.ToJsonString();
        var id = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes($"{DateTimeOffset.UtcNow:O}{stateText}")))[..10];
        var entry = new JsonObject
        {
            ["id"] = id,
            ["at"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["recipe"] = recipe,
            ["model"] = response.Model,
            ["requested_model"] = request.Model,
            ["latency_ms"] = (int)elapsed.TotalMilliseconds,
            ["state"] = stateText.Length > 4000 ? stateText[..4000] : stateText,
            ["questions"] = request.QuestionsJson(),
            ["answers"] = response.RawAnswers.DeepClone(),
        };
        Write(Path, entry);
        return id;
    }

    public static void Write(string path, JsonObject entry)
    {
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        File.AppendAllText(path, entry.ToJsonString() + "\n");
    }

    public static IEnumerable<JsonObject> Read(string path) =>
        File.Exists(path)
            ? File.ReadLines(path).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!.AsObject())
            : [];
}

static class LogCommands
{
    public static int Label(Args args)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine("""
                Usage: decide label ID QUESTION OUTCOME

                Records what really happened. OUTCOME is yes or no for a yes/no question, or the
                option key for a choice. Score questions are not calibrated.
                Example: decide label 3f9a1c2b7e cause flaky-test
                """);
            return 0;
        }
        var id = args.NextPositional() ?? throw new UsageException("label needs ID QUESTION OUTCOME");
        var question = args.NextPositional() ?? throw new UsageException("label needs ID QUESTION OUTCOME");
        var outcome = args.NextPositional() ?? throw new UsageException("label needs ID QUESTION OUTCOME");
        args.EnsureEmpty();
        var entry = DecisionLog.Read(DecisionLog.Path).LastOrDefault(e => (string?)e["id"] == id)
            ?? throw new UsageException($"no logged decision {id}");
        var kind = (string?)entry["questions"]?[question]?["type"] ?? throw new UsageException($"{id} has no question '{question}'");
        var valid = kind switch
        {
            "noul" => outcome is "yes" or "no",
            "choice" => entry["questions"]![question]!["criteria"]!.AsObject().ContainsKey(outcome),
            _ => throw new UsageException("score questions are not labelled"),
        };
        if (!valid)
        {
            throw new UsageException($"'{outcome}' is not a valid outcome for {question}");
        }
        DecisionLog.Write(DecisionLog.LabelsPath, new JsonObject
        {
            ["id"] = id,
            ["question"] = question,
            ["outcome"] = outcome,
            ["at"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
        });
        return 0;
    }

    public static int Calibrate(Args args)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine("""
                Usage: decide calibrate

                For every recipe/question pair with labels: count, Brier score (0 is perfect,
                0.25 is a coin flip for yes/no) and accuracy of the most likely answer. Use it to
                decide which questions are trustworthy enough to gate on.
                """);
            return 0;
        }
        args.EnsureEmpty();
        var entries = DecisionLog.Read(DecisionLog.Path).ToDictionary(e => (string)e["id"]!, e => e);
        var latest = DecisionLog.Read(DecisionLog.LabelsPath)
            .GroupBy(l => ((string)l["id"]!, (string)l["question"]!))
            .Select(g => g.Last());

        var rows = new Dictionary<string, (int Count, double Brier, int Correct)>();
        foreach (var label in latest)
        {
            if (!entries.TryGetValue((string)label["id"]!, out var entry))
            {
                continue;
            }
            var question = (string)label["question"]!;
            var outcome = (string)label["outcome"]!;
            var answer = entry["answers"]?[question];
            if (answer is null)
            {
                continue;
            }
            double brier;
            bool correct;
            if ((string?)answer["type"] == "noul")
            {
                var p = (double)answer["noul"]!;
                var y = outcome == "yes" ? 1.0 : 0.0;
                brier = (p - y) * (p - y);
                correct = (p >= 0.5) == (y == 1.0);
            }
            else
            {
                var probabilities = answer["probabilities"]!.AsObject();
                brier = probabilities.Sum(p => Math.Pow((double)p.Value! - (p.Key == outcome ? 1 : 0), 2));
                correct = (string?)answer["choice"] == outcome;
            }
            var key = $"{entry["recipe"]}/{question}";
            var row = rows.GetValueOrDefault(key);
            rows[key] = (row.Count + 1, row.Brier + brier, row.Correct + (correct ? 1 : 0));
        }

        if (rows.Count == 0)
        {
            Console.WriteLine("no labelled decisions yet: use 'decide label ID QUESTION OUTCOME'");
            return 0;
        }
        Console.WriteLine($"{"question",-32} {"n",4} {"brier",7} {"accuracy",9}");
        foreach (var (key, row) in rows.OrderBy(r => r.Key, StringComparer.Ordinal))
        {
            Console.WriteLine(string.Create(CultureInfo.InvariantCulture,
                $"{key,-32} {row.Count,4} {row.Brier / row.Count,7:0.000} {100.0 * row.Correct / row.Count,8:0}%"));
        }
        return 0;
    }

    public static int Show(Args args)
    {
        if (args.Flag("-h", "--help"))
        {
            Console.WriteLine("Usage: decide log [--last N]\n\nShows the most recent logged decisions, newest last.");
            return 0;
        }
        var last = (int)Input.Positive(args.Value("--last") ?? "10", "--last");
        args.EnsureEmpty();
        foreach (var entry in DecisionLog.Read(DecisionLog.Path).TakeLast(last))
        {
            var answers = entry["answers"]!.AsObject().Select(a => a.Value?["type"]?.GetValue<string>() switch
            {
                "noul" => $"{a.Key}={(double)a.Value!["noul"]!:0.00}",
                "choice" => $"{a.Key}={a.Value!["choice"]}",
                "score" => $"{a.Key}={(double)a.Value!["score"]!:0.00}",
                _ => a.Key,
            });
            Console.WriteLine($"{entry["id"]}  {entry["at"]?.GetValue<string>()[..19]}  {entry["recipe"],-12} {string.Join("  ", answers)}");
        }
        return 0;
    }
}

#region SystemOne client: copy this region into an app as it is
namespace SystemOne
{
    using System.Net;
    using System.Net.Http.Headers;
    using System.Text.Json.Nodes;

    /// <summary>A question asked of the model. Each maps to one entry in the request's questions object.</summary>
    public abstract record Question(string Instructions)
    {
        /// <summary>The API's question object.</summary>
        public abstract JsonObject ToJson();

        /// <summary>Parses a JSON object of named questions in the API's own shape.</summary>
        public static Dictionary<string, Question> ParseMany(string json)
        {
            var root = JsonNode.Parse(json) as JsonObject ?? throw new FormatException("questions must be a JSON object");
            var result = new Dictionary<string, Question>();
            foreach (var (name, node) in root)
            {
                var type = (string?)node?["type"];
                var instructions = (string?)node?["instructions"] ?? throw new FormatException($"{name} needs instructions");
                result[name] = type switch
                {
                    "noul" => new YesNoQuestion(instructions),
                    "choice" => new ChoiceQuestion(instructions, node!["criteria"]!.AsObject().ToDictionary(p => p.Key, p => (string)p.Value!)),
                    "score" => new ScoreQuestion(instructions, [.. node!["criteria"]!.AsArray().Select(a => (string)a!)]),
                    _ => throw new FormatException($"{name} has unknown type '{type}'; use noul, choice or score"),
                };
            }
            return result;
        }
    }

    /// <summary>Yes/no: the answer is the probability of yes. The API calls this type "noul".</summary>
    public sealed record YesNoQuestion(string Instructions) : Question(Instructions)
    {
        /// <inheritdoc />
        public override JsonObject ToJson() => new() { ["type"] = "noul", ["instructions"] = Instructions };
    }

    /// <summary>One of several named options; each option's description steers the model.</summary>
    public sealed record ChoiceQuestion(string Instructions, IReadOnlyDictionary<string, string> Options) : Question(Instructions)
    {
        /// <inheritdoc />
        public override JsonObject ToJson() => new()
        {
            ["type"] = "choice",
            ["instructions"] = Instructions,
            ["criteria"] = new JsonObject([.. Options.Select(o => KeyValuePair.Create(o.Key, (JsonNode?)JsonValue.Create(o.Value)))]),
        };
    }

    /// <summary>A position on an ordered scale of anchors, lowest first. The score is in [0, 1].</summary>
    public sealed record ScoreQuestion(string Instructions, IReadOnlyList<string> Anchors) : Question(Instructions)
    {
        /// <inheritdoc />
        public override JsonObject ToJson() => new()
        {
            ["type"] = "score",
            ["instructions"] = Instructions,
            ["criteria"] = new JsonArray([.. Anchors.Select(a => (JsonNode?)JsonValue.Create(a))]),
        };
    }

    /// <summary>An answer from the model.</summary>
    public abstract record Answer;

    /// <summary>Probability that the answer is yes.</summary>
    public sealed record YesNoAnswer(double Probability) : Answer;

    /// <summary>The most likely option, every option's probability, and the model's confidence.</summary>
    public sealed record ChoiceAnswer(string Choice, IReadOnlyDictionary<string, double> Probabilities, double Confidence) : Answer;

    /// <summary>A score in [0, 1], the probability of each anchor (by index), and confidence.</summary>
    public sealed record ScoreAnswer(double Score, IReadOnlyDictionary<int, double> Probabilities, IReadOnlyDictionary<int, string> Legend, double Confidence) : Answer;

    /// <summary>A request: a state (any JSON, often a string) and named questions about it.</summary>
    public sealed record DecisionRequest(string Model, JsonNode State, IReadOnlyDictionary<string, Question> Questions)
    {
        /// <summary>The questions object.</summary>
        public JsonObject QuestionsJson() =>
            new([.. Questions.Select(q => KeyValuePair.Create(q.Key, (JsonNode?)q.Value.ToJson()))]);

        /// <summary>The request body.</summary>
        public JsonObject ToJson() => new()
        {
            ["model"] = Model,
            ["state"] = State.DeepClone(),
            ["questions"] = QuestionsJson(),
        };
    }

    /// <summary>A parsed response. RawAnswers keeps the API's answers object for logging.</summary>
    public sealed record DecisionResponse(string Model, IReadOnlyDictionary<string, Answer> Answers, JsonObject RawAnswers, string? Id)
    {
        /// <summary>Parses a response body.</summary>
        public static DecisionResponse Parse(string json)
        {
            var root = JsonNode.Parse(json)?.AsObject() ?? throw new SystemOneException("empty response");
            if (root["error"] is { } error)
            {
                throw new SystemOneException((string?)error["message"] ?? error.ToJsonString());
            }
            var raw = root["answers"]?.AsObject() ?? throw new SystemOneException("response has no answers");
            var answers = new Dictionary<string, Answer>();
            foreach (var (name, node) in raw)
            {
                answers[name] = (string?)node?["type"] switch
                {
                    "noul" => new YesNoAnswer((double)node!["noul"]!),
                    "choice" => new ChoiceAnswer(
                        (string)node!["choice"]!,
                        node["probabilities"]!.AsObject().ToDictionary(p => p.Key, p => (double)p.Value!),
                        (double?)node["confidence"] ?? 0),
                    "score" => new ScoreAnswer(
                        (double)node!["score"]!,
                        node["probabilities"]!.AsObject().ToDictionary(p => int.Parse(p.Key, System.Globalization.CultureInfo.InvariantCulture), p => (double)p.Value!),
                        node["legend"]!.AsObject().ToDictionary(p => int.Parse(p.Key, System.Globalization.CultureInfo.InvariantCulture), p => (string)p.Value!),
                        (double?)node["confidence"] ?? 0),
                    var type => throw new SystemOneException($"answer {name} has unknown type '{type}'"),
                };
            }
            return new DecisionResponse((string?)root["model"] ?? "", answers, raw, (string?)root["id"]);
        }
    }

    /// <summary>The API refused, failed or could not be reached.</summary>
    public sealed class SystemOneException(string message) : Exception(message);

    /// <summary>
    /// POSTs to OpenRouter's System One endpoint. Sends a bearer token only when one is given:
    /// behind a proxy that injects the key for openrouter.ai, none is needed.
    /// Retries once on 429 or 5xx, honouring Retry-After up to ten seconds.
    /// </summary>
    public sealed class SystemOneClient : IDisposable
    {
        /// <summary>The free decision model.</summary>
        public const string DefaultModel = "inception/mercury-decide:free";

        /// <summary>The endpoint.</summary>
        public static readonly Uri Endpoint = new("https://openrouter.ai/api/v1/systemone");

        readonly HttpClient _http;

        /// <summary>Creates a client; <paramref name="apiKey"/> may be null behind a key-injecting proxy.</summary>
        public SystemOneClient(string? apiKey, TimeSpan timeout, Uri? endpoint = null)
        {
            _http = new HttpClient { Timeout = timeout, BaseAddress = endpoint ?? Endpoint };
            if (!string.IsNullOrEmpty(apiKey))
            {
                _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
            }
            _http.DefaultRequestHeaders.Add("X-Title", "decide");
        }

        /// <summary>Uses OPENROUTER_API_KEY and DECIDE_URL when set.</summary>
        public static SystemOneClient FromEnvironment(TimeSpan timeout) => new(
            Environment.GetEnvironmentVariable("OPENROUTER_API_KEY"),
            timeout,
            Environment.GetEnvironmentVariable("DECIDE_URL") is { Length: > 0 } url ? new Uri(url) : null);

        /// <summary>Sends the request and parses the answers.</summary>
        public async Task<DecisionResponse> DecideAsync(DecisionRequest request, CancellationToken cancellationToken = default)
        {
            var body = request.ToJson().ToJsonString();
            for (var attempt = 0; ; attempt++)
            {
                HttpResponseMessage response;
                try
                {
                    using var content = new StringContent(body, System.Text.Encoding.UTF8, "application/json");
                    response = await _http.PostAsync((Uri?)null, content, cancellationToken);
                }
                catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException && !cancellationToken.IsCancellationRequested)
                {
                    throw new SystemOneException($"request failed: {ex.Message}");
                }
                using (response)
                {
                    var text = await response.Content.ReadAsStringAsync(cancellationToken);
                    var retryable = response.StatusCode == HttpStatusCode.TooManyRequests || (int)response.StatusCode >= 500;
                    if (retryable && attempt == 0)
                    {
                        var wait = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(2);
                        await Task.Delay(wait > TimeSpan.FromSeconds(10) ? TimeSpan.FromSeconds(10) : wait, cancellationToken);
                        continue;
                    }
                    if (!response.IsSuccessStatusCode)
                    {
                        var hint = response.StatusCode == HttpStatusCode.Unauthorized ? " (set OPENROUTER_API_KEY)" : "";
                        string detail;
                        try
                        {
                            detail = (string?)JsonNode.Parse(text)?["error"]?["message"] ?? text;
                        }
                        catch (System.Text.Json.JsonException)
                        {
                            detail = text;
                        }
                        throw new SystemOneException($"HTTP {(int)response.StatusCode}: {detail.Trim()}{hint}");
                    }
                    return DecisionResponse.Parse(text);
                }
            }
        }

        /// <inheritdoc />
        public void Dispose() => _http.Dispose();
    }
}
#endregion
