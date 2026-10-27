"""Seven source-defined RFP summary questions; bump the set ID for content changes."""

QUESTION_SET_ID = "GENERAL_RFP_V1"

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

QUESTIONS = [
    {
        "question_id": "Q001",
        "category": "Project Overview",
        "question": "What is the project's purpose, business need, objectives, intended outcomes, "
        "location, capacity or scale, and key stakeholders?",
        "answer_type": "structured_summary",
        "instructions": [
            "Extract purpose, need, objectives and outcomes.",
            "Capture project name, location, scale and procuring entity where stated.",
            "Separate stated facts from interpretation.",
        ],
    },
    {
        "question_id": "Q002",
        "category": "Project Scope",
        "question": "What work, services, systems, technical activities, implementation activities "
        "and operational responsibilities are included in the project scope?",
        "answer_type": "structured_summary",
        "instructions": [
            "Identify explicit in-scope activities, assets, systems and responsibilities.",
            "Capture phases and boundaries.",
            "Do not infer scope merely because a topic is mentioned.",
        ],
    },
    {
        "question_id": "Q003",
        "category": "Key Deliverables",
        "question": "What are the required project deliverables, outputs, services, documents, "
        "facilities, guarantees and handover items?",
        "answer_type": "structured_list",
        "instructions": [
            "List each deliverable separately.",
            "Capture responsible party, due date and acceptance criteria only when stated.",
            "Separate bid-submission requirements from execution deliverables where possible.",
        ],
    },
    {
        "question_id": "Q004",
        "category": "Assumptions",
        "question": "What assumptions are stated about site conditions, data, infrastructure, "
        "resources, dependencies, responsibilities and operating conditions?",
        "answer_type": "structured_list",
        "instructions": [
            "Prioritize explicit assumptions.",
            "Label any inference as an inference.",
            "Do not treat missing information as an assumption.",
        ],
    },
    {
        "question_id": "Q005",
        "category": "Constraints",
        "question": "What mandatory technical, regulatory, environmental, safety, financial, "
        "schedule, geographic, resource or contractual constraints apply?",
        "answer_type": "structured_list",
        "instructions": [
            "Capture mandatory limits, standards, deadlines and restrictions.",
            "Preserve numeric thresholds and clause references.",
            "Distinguish mandatory constraints from preferences.",
        ],
    },
    {
        "question_id": "Q006",
        "category": "Exclusions",
        "question": "What activities, systems, services, features, responsibilities or "
        "deliverables are explicitly excluded from the project?",
        "answer_type": "structured_list",
        "instructions": [
            "Report explicit exclusions and clear responsibility boundaries only.",
            "Silence is not an exclusion.",
            "If none are found, say no explicit exclusion was identified in the evidence reviewed.",
        ],
    },
    {
        "question_id": "Q007",
        "category": "Milestones & Timeline",
        "question": "What phases, milestones, bid dates, project deadlines, durations, "
        "dependencies, commissioning dates and acceptance checkpoints are specified?",
        "answer_type": "structured_list",
        "instructions": [
            "Capture dates, durations and sequence exactly as stated.",
            "Distinguish procurement dates from project delivery milestones.",
            "Do not invent or calculate dates without evidence.",
        ],
    },
]
