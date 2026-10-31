# FP spot-check: sweep-a, judge claude-sonnet-5-5, seed 20261031

30 of 692 false positives. For each, `verdict` is `real` (a defect the goldens miss), `not-real`, or `unsure`. Read the PR before you decide; the key is below the table so the arm can't sway the call.

| # | PR | candidate | verdict |
|---|---|---|---|
| 1 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/5 | Browser reporting serializer in browser_reporting_collector.py requires destination and attempts fields that real browsers (per the W3C serialize reports algorithm, e.g. Chrome) don't send, so real reports fail with 422 and one bad report rejects the whole batch; tests don't catch this because the fixture includes those fields | real |
| 2 | https://github.com/calcom/cal.com/pull/7232 | The cron job in scheduleEmailReminders.ts uses the SendGrid `client` from `@sendgrid/client` but only calls `sgMail.setApiKey(...)`, never `client.setApiKey(...)`. The client may have no API key, so cancel requests fail with auth errors, the catch only logs them, and cancelled/rescheduled bookings still send their reminder emails. | real |
| 3 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/3 | Blocked-email check in `BlockedEmail.should_block?` (app/models/blocked_email.rb:79, `BlockedEmail.where(email: email).first`) is case-sensitive because neither `User` nor `BlockedEmail` normalizes/downcases email, so a blocked address like bad@spamclub.com can be bypassed with Bad@SpamClub.com. Fix: downcase on both sides (before_validation in BlockedEmail using Email.downcase, and in the lookup) or query with lower(email) = ?. | real |
| 4 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/5 | Tests for the replay summarize breadcrumbs merge use seconds for both error and replay timestamps, so they do not catch the seconds vs milliseconds mismatch. | real |
| 5 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/4 | disqus.thor drops created_at: Date.parse(t[:created_at]), so imported topics get the import time instead of the original Disqus thread date | real |
| 6 | https://github.com/keycloak/keycloak/pull/37634 | Unused import of org.keycloak.protocol.oidc.grants.TokenExchangeGrantTypeFactory in StandardTokenExchangeProvider | not-real |
| 7 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/3 | upsampled_count() computes toInt64(sum(sample_weight)) with no fallback for missing sample_weight, so events without a weight (no error_sampling context, invalid rate, or stored before the project was allowlisted) are skipped as NULL, causing undercounts or 0/NULL results and sharp drops in count() charts; it should treat a missing weight as 1 (e.g. ifNull(sample_weight, 1)) and have a test for an event without error_sampling context | real |
| 8 | https://github.com/calcom/cal.com/pull/10967 | `handleCancelBooking` recurring-bookings deletion block sits inside the per-reference loop, running N times and issuing duplicate deletes, and only reads the first calendar reference of each remaining booking so other members' events are never deleted | real |
| 9 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/7 | In mobile/topic-post.scss (`h3`), the light-theme heading color changed from 20% to 50% lightness, making it lighter and lowering contrast; desktop uses 20/80 correctly. Should be dark-light-choose(scale-color($primary, $lightness: 20%), scale-color($secondary, $lightness: 80%)). | real |
| 10 | https://github.com/grafana/grafana/pull/97529 | server.Stop still sets s.initErr to 'service is stopping'/'service is stopped', but with per-handler Init calls removed nothing reads initErr, so requests after Stop go straight to the backend and initErr is dead code as a shutdown guard. Either remove it or check it in the handlers. | real |
| 11 | https://github.com/getsentry/sentry/pull/80168 | The stale comment `# TODO: This will be a stateful detector when we build that abstraction` above MetricAlertDetectorHandler should be removed or updated. | not-real |
| 12 | https://github.com/grafana/grafana/pull/103633 | In Check (service.go:123-139), when the cached permission map says deny, the code falls through to getIdentityPermissions, which no longer reads the cache and always runs the basic-role lookup, team lookup and permissionStore.GetUserPermissions. Every first-time denied check for a resource therefore hits the database. Since the denial cache is keyed per (name, parent) and singleflight only merges concurrent requests, users checking many inaccessible resources (search filtering, folder listings) trigger one DB round-trip per resource, where before it was a single cache lookup. | real |
| 13 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/5 | Mutual-exclusion checks for age/timestamp use truthiness (self.initial_data.get('age')), so age: 0 slips past the check; should use 'age' in self.initial_data | not-real |
| 14 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/3 | The 60s eligibility cache in error_upsampling.py adds a Redis/memcached round-trip in front of the already in-process cached options.get, making requests slower rather than faster | not-real |
| 15 | https://github.com/calcom/cal.com/pull/11059 | Office365 CalendarService now throws when the token fails schema validation and the diagnostic log was removed, changing previously tolerant behavior on an existing production path | unsure |
| 16 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/2 | Adding `render :show` inside `perform_show_response` in topics_controller.rb draws the page and layout before `canonical_url` is set in `show` (line 87), so `@canonical_url` is nil and every topic page loses its `<link rel="canonical">` tag, an SEO regression | real |
| 17 | https://github.com/getsentry/sentry/pull/93824 | spans.buffer.max-flush-segments now applies per flusher process rather than to the whole consumer, so with N processes up to N times as many segments are loaded per cycle, silently changing the option's meaning unless documented. | not-real |
| 18 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/4 | absolutize_urls breaks protocol-relative URLs (//cdn.example.com/a.png becomes http://blog.com/cdn.example.com/a.png) because start_with?('/') matches and the leading slashes are stripped | real |
| 19 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/2 | paginator.py has three blank lines before OptimizedCursorPaginator and trailing whitespace in its docstring | not-real |
| 20 | https://github.com/calcom/cal.com/pull/8087 | The import() calls in appStore (packages/app-store/index.ts) run eagerly when the object literal is built, so all 28 app packages load at once and nothing is lazy-loaded. The change forces await into about 15 call sites and makes several sync functions async with no load-time or bundle benefit. Fix: store loader functions (() => import(...)) and call them on demand. | real |
| 21 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1 | OptimizedCursorPaginator.get_result duplicates BasePaginator.get_result; its else branch is identical to the base logic, so the class adds nothing beyond the broken negative-offset path | not-real |
| 22 | https://github.com/calcom/cal.com/pull/7232 | Indentation was stripped inside a commented-out block near line 900 of workflows.tsx, an apparent accidental formatter or editor change | not-real |
| 23 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/7 | In mobile/topic-post.scss:182, the `h3` link colour changed in the light theme from 20% to 50% lightness for both themes, so it looks the same as the `h4` below it, unlike the correctly converted desktop/topic-post.scss:321. Should be dark-light-choose(scale-color($primary, $lightness: 20%), scale-color($secondary, $lightness: 80%)). | real |
| 24 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1 | The negative-offset branch is inconsistent with other paginators (OffsetPaginator, MergingOffsetPaginator, CombinedQuerysetPaginator, ChainPaginator, CallbackPaginator), which raise BadPaginationError for negative offsets (checked by test_negative_offset), and its stated goal of accessing data beyond normal pagination bounds is a red flag | real |
| 25 | https://github.com/grafana/grafana/pull/90045 | The new Mode 3 playlist integration tests actually run in Mode 1 because SetDualWritingMode defaults to Mode 1 and only handles 1→2 and 2→1 transitions, so they never exercise Mode 3 code, giving false coverage; Mode 3 is also unreachable in production via this path | real |
| 26 | https://github.com/keycloak/keycloak/pull/36880 | checkAdminRoles does not protect realm-management in V2 because root.getRealmPermissionsClient() returns the admin-permissions client rather than realm-management. Realm-management admin roles fall into the 'not an admin client' branch and are allowed. | real |
| 27 | https://github.com/ai-code-review-evaluation/sentry-greptile/pull/5 | Error timestamps from nodestore events (epoch seconds) are compared with replay rrweb segment timestamps (epoch milliseconds) in fetch_error_details/gen_request_data, so all errors are emitted before the first breadcrumb and chronological ordering fails on real data. Tests hide this by using seconds for both; fix by multiplying error timestamp by 1000 and using realistic millisecond timestamps in tests. | real |
| 28 | https://github.com/ai-code-review-evaluation/discourse-graphite/pull/1 | `tempfile.size` may return a stale value after the file is rewritten externally in place by downsize without being reopened, affecting both the loop condition and the later `tempfile.size` passed to `Upload.create_for`; should use `File.size(tempfile.path)` | unsure |
| 29 | https://github.com/grafana/grafana/pull/90045 | Legacy write goroutines in Create, Delete, Update and DeleteCollection use context.WithTimeoutCause on the request ctx, so the legacy writes can be cancelled when the HTTP handler returns (context canceled), causing legacy and storage to drift apart. Fix: use context.WithoutCancel(ctx) and log errors inside the goroutine instead of only recording a metric. The same pattern already exists in dualwriter_mode1.go. | real |
| 30 | https://github.com/grafana/grafana/pull/103633 | NoopCache in authz/rbac.go is exported but only used within that file; it should be unexported (noopCache), and its receiver name `lc` was copied from LocalCache. | not-real |

## Key

| # | arm |
|---|---|
| 1 | jobd-claude-opus-5-5.xhigh |
| 2 | jobd-claude-opus-5-5.medium |
| 3 | jobd-claude-sonnet-5-5.high |
| 4 | jobd-claude-sonnet-5-5.xhigh |
| 5 | jobd-claude-sonnet-5-5.xhigh |
| 6 | jobd-claude-sonnet-5-5.xhigh |
| 7 | jobd-claude-opus-5-5.xhigh |
| 8 | jobd-claude-sonnet-5-5.xhigh |
| 9 | jobd-claude-sonnet-5-5.xhigh |
| 10 | jobd-claude-sonnet-5-5.xhigh |
| 11 | jobd-claude-sonnet-5-5.high |
| 12 | jobd-claude-opus-5-5.medium |
| 13 | jobd-claude-opus-5-5.high |
| 14 | jobd-claude-opus-5-5.medium |
| 15 | jobd-claude-opus-5-5.high |
| 16 | jobd-claude-opus-5-5.xhigh |
| 17 | jobd-claude-opus-5-5.xhigh |
| 18 | jobd-claude-opus-5-5.xhigh |
| 19 | jobd-claude-sonnet-5-5.high |
| 20 | jobd-claude-sonnet-5-5.xhigh |
| 21 | jobd-claude-sonnet-5-5.xhigh |
| 22 | jobd-claude-sonnet-5-5.medium |
| 23 | jobd-claude-opus-5-5.medium |
| 24 | jobd-claude-opus-5-5.xhigh |
| 25 | jobd-claude-opus-5-5.xhigh |
| 26 | jobd-claude-opus-5-5.xhigh |
| 27 | jobd-claude-sonnet-5-5.high |
| 28 | jobd-claude-sonnet-5-5.medium |
| 29 | jobd-claude-opus-5-5.medium |
| 30 | jobd-claude-sonnet-5-5.xhigh |
