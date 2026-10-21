-- Destination schema, for reference.
--
-- The pipeline applies this itself on every run (see src/load.ensure_tables),
-- so running this file by hand is optional. It is kept in the repository so
-- the tables can be read without reading the Python.

IF OBJECT_ID('dbo.agent_behavior', 'U') IS NULL
CREATE TABLE dbo.agent_behavior (
    agent NVARCHAR(200),
    report_date DATE,
    agent_id INT,
    campaign NVARCHAR(150),
    inbound_total INT,
    inbound_pct FLOAT,
    inbound_rejected INT,
    inbound_rejected_pct FLOAT,
    inbound_answered INT,
    inbound_answered_pct FLOAT,
    outbound_total INT,
    outbound_pct FLOAT,
    outbound_rejected INT,
    outbound_rejected_pct FLOAT,
    outbound_answered INT,
    outbound_answered_pct FLOAT,
    outbound_dialing INT,
    outbound_dialing_pct FLOAT,
    calls_with_hold INT,
    calls_with_hold_pct FLOAT,
    avg_response_time_inbound FLOAT,
    avg_response_time_outbound FLOAT,
    load_date DATETIME DEFAULT GETDATE()
);

IF OBJECT_ID('dbo.agent_operational_states', 'U') IS NULL
CREATE TABLE dbo.agent_operational_states (
    report_date DATE,
    time_interval NVARCHAR(50),
    agent_id INT,
    agent NVARCHAR(200),
    campaign_id INT,
    campaign NVARCHAR(150),
    login_time FLOAT,
    net_login_time FLOAT,
    available_time FLOAT,
    preview_time FLOAT,
    dialing_time FLOAT,
    ringing_time FLOAT,
    talking_time FLOAT,
    talking_inbound_time FLOAT,
    talking_outbound_time FLOAT,
    hold_time FLOAT,
    acw_time FLOAT,
    other_crm_time FLOAT,
    pause_time FLOAT,
    daily_login_time FLOAT,
    daily_net_login_time FLOAT,
    daily_available_time FLOAT,
    daily_preview_time FLOAT,
    daily_dialing_time FLOAT,
    daily_ringing_time FLOAT,
    daily_talking_time FLOAT,
    daily_talking_inbound_time FLOAT,
    daily_talking_outbound_time FLOAT,
    daily_hold_time FLOAT,
    daily_acw_time FLOAT,
    daily_other_crm_time FLOAT,
    daily_pause_time FLOAT,
    load_date DATETIME DEFAULT GETDATE()
);
