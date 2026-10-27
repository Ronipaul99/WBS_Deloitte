# Outstanding qualification inputs

Step 1 remains partially complete. Local tests are not a substitute for these gates.

1. Mac gateway approved HTTPS base URL, exact API protocol and authentication scheme,
   exact Llama model ID, availability window, proposed context/output ceilings, and a
   securely provisioned credential. An unspecified public gateway does not establish
   OpenAI API compatibility. Do not paste credentials into documents or chat.
2. An accessible OpenAI model/API project and securely provisioned credential, plus
   an explicit synthetic-probe request/token/cost limit. No model ID is hard-coded.
3. Permission and a safe channel to execute the actual synthetic probes through the
   model worker network path. The current task forbids live VM changes; this run did
   not access it. Local laptop connectivity would not prove worker reachability.
4. Actual schema/tool/refusal/truncation/usage/error/latency observations for each
   intended demo profile. Verify conservative context/output limits rather than
   importing fixture or marketing values. Keep all real profiles disabled until qualified.
5. PostgreSQL checkpointer choice and proof that every operation enforces trusted
   tenant/run transaction scope under the actual runtime role. The SQLite spike is
   functional evidence and an explicit unresolved production isolation decision.
   Production migrations, persistence, leases and recovery wiring belong to Steps 2/5.
6. Claude must pass its own adapter and live qualification before enablement; the
   local canonical fixture does not satisfy that requirement.

No provider adapter, credential management, endpoint policy, production graph,
source reader, summary generation, verification agent, route or UI is enabled.
