# tool_descriptions v2
Rewritten descriptions for the nine marketplace tools (R&D question A, "best set"). Written before the
tool design study was run and not edited afterwards. Each section is `## tool_name`, a description, then
optional `- arg: text` lines that replace that argument's description. Format is parsed by
evals/runners/tool_design.py. Pattern used: say what the tool is for, say when NOT to use it and which tool to
use instead, and state the required arguments in plain words.

## _system_prompt
You are the tool-calling layer of a freelancing assistant. Read the user's request and call exactly one tool that fulfils it, with arguments copied exactly from the request. Do not ask questions and do not answer in prose.

## search_jobs
Use this to FIND jobs when you do not have a job id: search the job feed by a keyword and optionally narrow it to one persona feed (ai_ml, web or data). Returns a list of short job records. Do NOT use it to read one specific job (use get_job) or to learn about a client (use get_client_history).
- query: Keyword or phrase to look for in job titles, descriptions and skills, for example FastAPI.
- limit: Maximum number of jobs to return. Only set it when the user names a number.
- persona: Persona feed to restrict to. One of ai_ml, web, data. Leave out unless the user names a persona.

## get_job
Use this when you already have ONE job id (looks like dev-web-0001) and need its details: title, description, budget, required skills, duration and the Connects cost to apply to that job. Do NOT use it to browse or search (use search_jobs). The Connects cost of applying to a job is in this result, not in get_connects_balance.
- job_id: The exact job id, for example dev-web-0001.

## get_client_history
Use this when you have a CLIENT id (looks like c012) and want that client's public track record: payment verified or not, total spent, hire rate, average rating, reviews. It takes a client id, not a job id. Do NOT use it to read a job post (use get_job) or to read chat messages (use list_messages).
- client_id: The exact client id, for example c012.

## get_connects_balance
Use this only to learn how many Connects the freelancer has LEFT in their own account. It takes no arguments. It does not tell the cost of a particular job (that is in get_job) and it does not show platform rules (use get_policy).

## get_policy
Use this to read the current PLATFORM rules: Connects multiplier, boost fee, minimum job budget, daily proposal cap, rate limit, link rules and the list of rules proposals must follow. It takes no arguments. It is not about one job or one client.

## list_messages
Use this to READ existing chat messages between the freelancer and clients. Give a client id to see only that client's conversation, or give nothing to list every message. This tool never sends anything (use send_message to write to a client).
- client_id: Optional client id, for example c000. Leave out to list all messages.

## create_proposal_draft
Use this to SAVE a proposal as a draft on the server. It spends no Connects and the client sees nothing. Use it when the user says draft, save or store. If the user wants the proposal actually delivered to the client, use submit_proposal instead. Set dry_run to true only when the user asks to preview without storing.
- job_id: The job id the proposal is for, for example dev-web-0001.
- cover_letter: The full proposal text, exactly as the user gave it.
- bid_amount: The price in USD as a number.
- idempotency_key: The key the user gave for this write, copied exactly.
- dry_run: True only if the user asks to preview or not to store. Otherwise false.

## submit_proposal
Use this to actually SEND a proposal to the client. It spends Connects and cannot be undone, so use it only when the user says submit, send or apply for real. To only save a draft use create_proposal_draft. If the user asks what WOULD be sent or the cost without sending, still use this tool and set dry_run to true.
- job_id: The job id the proposal is for, for example dev-web-0001.
- cover_letter: The full proposal text, exactly as the user gave it.
- bid_amount: The price in USD as a number.
- idempotency_key: The key the user gave for this write, copied exactly.
- dry_run: True if the user wants a preview of the payload and Connects cost with nothing sent. False when the user wants it sent for real.

## send_message
Use this to WRITE a chat message to a client. Use it when the user wants to reply, tell or message a client. To read messages use list_messages instead. Set dry_run to true when the user asks to preview the message without sending it.
- client_id: The client id to message, for example c000.
- text: The message text, exactly as the user gave it.
- idempotency_key: The key the user gave for this write, copied exactly.
- dry_run: True only if the user asks to preview without sending. Otherwise false.
