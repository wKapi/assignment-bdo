-- HR — SQLite სქემა
--
-- თარიღები TEXT-ში ISO 8601 ფორმატით ინახება ('YYYY-MM-DD'), დროის
-- ნიშნულები — 'YYYY-MM-DDTHH:MM:SS'. SQLite-ს ცალკე DATE ტიპი არ აქვს,
-- ხოლო ISO ტექსტის ლექსიკოგრაფიული შედარება ქრონოლოგიურს ემთხვევა.

DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS leave_proposals;
DROP TABLE IF EXISTS leave_requests;
DROP TABLE IF EXISTS leave_entitlements;
DROP TABLE IF EXISTS public_holidays;
DROP TABLE IF EXISTS leave_types;
DROP TABLE IF EXISTS employees;

-- თანამშრომლები
CREATE TABLE employees (
    employee_id        TEXT PRIMARY KEY,
    full_name          TEXT NOT NULL,
    email              TEXT NOT NULL UNIQUE,
    department_code    TEXT NOT NULL,
    department_name    TEXT NOT NULL,
    job_title          TEXT NOT NULL,
    employment_type    TEXT NOT NULL,
    start_date         TEXT NOT NULL,
    probation_end_date TEXT,
    manager_id         TEXT REFERENCES employees (employee_id),
    status             TEXT NOT NULL DEFAULT 'active'
);

-- შვებულების სახეები

CREATE TABLE leave_types (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    day_unit            TEXT CHECK (day_unit IN ('working', 'calendar')),
    -- ANNUAL-ისთვის NULL: ოდენობა სტაჟზეა დამოკიდებული (მუხლი 4.1)
    annual_limit_days   INTEGER,
    self_service        INTEGER NOT NULL CHECK (self_service IN (0, 1)),
    assistant_supported INTEGER NOT NULL CHECK (assistant_supported IN (0, 1)),
    policy_reference    TEXT
);

-- წლიური კუთვნილი დღეები

CREATE TABLE leave_entitlements (
    employee_id       TEXT NOT NULL REFERENCES employees (employee_id),
    year              INTEGER NOT NULL,
    leave_type        TEXT NOT NULL REFERENCES leave_types (code),
    entitled_days     INTEGER NOT NULL,
    -- წინა წლიდან გადმოტანილი *საწყისი* რაოდენობა, არა დარჩენილი ნაშთი
    -- (მუხლი 4.7). ეხება მხოლოდ ANNUAL-ს.
    carried_over_days INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_id, year, leave_type)
);

-- შვებულების მოთხოვნები 

CREATE TABLE leave_requests (
    request_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL REFERENCES employees (employee_id),
    leave_type  TEXT NOT NULL REFERENCES leave_types (code),
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    days        INTEGER NOT NULL CHECK (days > 0),
    status      TEXT NOT NULL
                CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    created_at  TEXT NOT NULL,
    created_via TEXT NOT NULL CHECK (created_via IN ('portal', 'assistant')),
    comment     TEXT,
    decided_by  TEXT REFERENCES employees (employee_id),
    decided_at  TEXT,
    CHECK (end_date >= start_date)
);

CREATE INDEX idx_requests_employee_type
    ON leave_requests (employee_id, leave_type, start_date);
CREATE INDEX idx_requests_status
    ON leave_requests (status);

-- უქმე დღეები (მუხლი 2.3) 
CREATE TABLE public_holidays (
    date TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

-- ასისტენტის შეთავაზებები 
--
-- მუხლი 12.2: მოთხოვნის შექმნამდე ასისტენტი სახეს, თარიღებსა და დღეებს
-- აჩვენებს და მკაფიო დადასტურებას ითხოვს. აქ ინახება სწორედ ეს შეთავაზება.
-- `request_id` NULL-ია, სანამ თანამშრომელი არ დაადასტურებს; დადასტურების
-- შემდეგ ივსება და განმეორებითი დადასტურებისას იგივე ID ბრუნდება


CREATE TABLE leave_proposals (
    proposal_id     TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    employee_id     TEXT NOT NULL REFERENCES employees (employee_id),
    leave_type      TEXT NOT NULL REFERENCES leave_types (code),
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    days            INTEGER NOT NULL,
    reason          TEXT,
    created_at      TEXT NOT NULL,
    confirmed_at    TEXT,
    request_id      INTEGER REFERENCES leave_requests (request_id),
    UNIQUE (conversation_id, proposal_id)
);

CREATE INDEX idx_proposals_conversation
    ON leave_proposals (conversation_id, employee_id);

-- აუდიტის
--
-- მუხლი 12.4: ჯანმრთელობის დეტალები აქ არ იწერება — მხოლოდ სახე,
-- თარიღები და შედეგი.

CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('employee', 'hr', 'system')),
    actor_id   TEXT,
    tool       TEXT NOT NULL,
    args_json  TEXT,
    result     TEXT
);

CREATE INDEX idx_audit_ts ON audit_log (ts);
