
Research Status:
  Status: completed
  Task ID: eebf04c6-b3cc-4220-9c0a-56c929594abe
  Sources found: 55

Report:
# Comprehensive Legal and Technical Analysis of Restaurant Promotion Aggregation
in Qatar

## Technical Landscapes of Qatari Food Delivery Platforms

The on-demand delivery ecosystem in the State of Qatar has evolved into a highly
consolidated market dominated by three primary platforms: Talabat, Snoonu, and 
Rafeeq.[1, 2] To evaluate the feasibility of establishing a third-party 
promotional aggregator, the underlying technical frameworks, developer portals, 
and integration middleware of these platforms must be analyzed.

### Talabat Partner and Promotions APIs

Talabat operates a highly structured, enterprise-grade integration 
infrastructure managed under its parent group, Delivery Hero.[3, 4] This API 
environment is classified into two distinct operational categories:

1. **Integration Middleware APIs:** Endpoints designed for Point-of-Sale (POS) 
middleware and third-party aggregator plugins.[4]
2. **Plugin APIs:** Endpoints implemented directly by POS partners to receive 
order events, menu synchronization requests, and real-time merchant status 
updates.[4]

The Talabat Promotions API is restricted to registered, active merchant 
partners.[3] It is not exposed to the public or third-party marketing 
aggregators.[3] To access this system, a restaurant must utilize the Shop 
Integrations Plugin inside the self-service Talabat Partner Portal.[3] Gaining 
credentials requires an active account manager to generate a unique `client_id` 
and `client_secret`.[3] This process is limited to a maximum of ten active 
Client IDs per merchant chain.[3]

The authentication and authorization lifecycle relies on a secure OAuth 2.0 
Client Credentials Flow.[3, 5] 

* **Token Lifecycle:** An HTTP `POST` request must be executed against the token
generation gateway:
  `https://talabat.partner.deliveryhero.io/v2/oauth/token`.[3]
  The request payload is formatted as `application/x-www-form-urlencoded` 
containing the client credentials.[3] Upon validation, the server issues a 
Bearer JSON Web Token (JWT) with an expiration window of exactly two hours 
(`expires_in: 7200`).[3] POS partners are required to cache and reuse this token
to avoid triggering rate-limiting protocols.[5]
* **Rate Limiting:** The token generation endpoint enforces a strict limit of 50
requests per minute per Client ID.[3] Exceeding this limit results in an `HTTP 
429 Too Many Requests` error.[3]
* **Promotional Orchestration:** Promotional campaigns are established 
asynchronously using a `PUT` endpoint, which generates background processing 
jobs.[3, 5] Status tracking is performed via a corresponding `GET` endpoint, 
while real-time order modifications or promo application logs are dispatched to 
partner-defined webhooks.[3, 5]

For merchants with lower technical integration capabilities, Talabat provides a 
Secure File Transfer Protocol (SFTP) option.[6] This allows partners to perform 
bulk promotional updates by uploading structured CSV templates to a central SFTP
server, bypasses real-time REST API overhead.[6] For high-volume locations, 
Talabat supports real-time picking integrations via the Pelican Picking Android 
application or direct Partner Picking REST APIs to manage order flows 
programmatically.[7]

### Snoonu S-Cloud and Merchant Portal

Snoonu is Qatar's rapidly growing local super-app.[1, 8] It operates a closed 
ecosystem designed to protect proprietary merchant agreements, customer 
engagement analytics, and on-demand logistical intelligence.[9, 10]

* **S-Cloud Architecture:** Licensing and platform integration are managed 
through Snoonu's proprietary, white-label "S-Cloud" framework.[9] This 
infrastructure exposes RESTful APIs to license holders.[9] It includes core 
modules such as a Consumer Native App, a Merchant Management Dashboard, and a 
Driver App with real-time fleet optimization and intelligent routing.[9] These 
APIs are strictly operational and are not open to the public for third-party 
scraping or read-only aggregation.[9]
* **Merchant Engagement Tools:** Standard merchants interact with the platform 
through the Snoonu Portal (available via mobile and web interfaces).[10] This 
portal serves as the entry point for uploading menus, establishing promotional 
pricing, and tracking orders in real time.[8, 10]
* **Dynamic Engagement Tools:** Snoonu integrates with third-party customer 
engagement platforms, such as Braze, to drive customer retention.[11] This 
infrastructure utilizes HTML-based in-app messaging, dynamic push notifications,
and webhooks to assign promotional codes automatically to user profiles.[11] 
These codes are mapped via secure, internal APIs connected to Snoonu's 
proprietary discount generation system.[11]

### Rafeeq AWS Serverless Stack and Merchant Flows

Rafeeq, a 100% Qatari-owned lifestyle and delivery super-app, operates an 
advanced, modern cloud-native architecture.[2, 12]

* **Infrastructure Design:** Rafeeq's backend is hosted on Amazon Web Services 
(AWS) serverless architecture, provisioned programmatically using Terraform 
(Infrastructure as Code).[12] Node.js and TypeScript power the execution 
layers.[12]
* **Data Pipelines:** Analytical and operational data flows are orchestrated 
between AWS S3 storage buckets, API Gateways, EventBridge event buses, and 
Google BigQuery data warehouses.[12]
* **B2B Integration Footprint:** Rafeeq does not expose any public APIs for 
third-party developers, coupon engines, or public aggregators. Similar to 
Snoonu, Rafeeq's integration landscape is restricted to internal plugins, 
AWS-managed API gateways, and secured POS middleware partnerships.[4, 12, 13] 
These technologies are configured exclusively to capture merchant transactions, 
dispatch fleet drivers, and synchronize localized inventories.[13] The app also 
features "Rafeeq Stars," an influencer-driven store experience that allows 
creators to sell exclusive items and launch targeted promotions.[2]

| Platform Feature | Talabat API/SFTP | Snoonu S-Cloud | Rafeeq Serverless |
| :--- | :--- | :--- | :--- |
| **Public API Access** | None (Walled Garden) [3] | None (Strictly Closed) [9] 
| None (Proprietary Gateway) [3] |
| **B2B Integration Method** | OAuth 2.0 / SFTP / POS Middleware [3, 4, 6] | 
S-Cloud REST Modules / Merchant App [9, 10] | AWS API Gateway / Secure 
Middleware [12, 13] |
| **Token Validity** | 2 Hours (Rolling Refresh) [3] | N/A (Internal 
Tokenization) [9] | N/A (AWS IAM / Event-Driven) [12] |
| **Promo Sync Pipeline** | REST PUT Endpoint / CSV Bulk Upload [3, 6] | Braze 
Webhook / CRM Auto-generation [11] | EventBridge Trigger / BigQuery Log [12] |

---

## Social Media Business Discovery and B2B Coupon Alliances

Given the programmatic barriers of the major delivery apps, third-party 
aggregators must seek alternative, open-access, or B2B-partnered data streams to
retrieve localized promotional data.

### Instagram Graph API and Business Discovery

For aggregators tracking restaurant promotions organically, the Instagram Graph 
API is a compliance-friendly tool. It allows the extraction of public 
promotional creatives published by restaurant accounts.[14, 15]

* **Core Mechanics of Business Discovery:** An authorized aggregator must 
register a Meta Developer Application, link it to an active Facebook Page, and 
authenticate via an Instagram Business or Creator account.[15, 16] Utilizing the
`Business Discovery` endpoint, the authenticated account can programmatically 
query public metadata and media from any other Instagram Business or Creator 
profile in Qatar.[15, 16]
* **Query Structure:** The endpoint is called via a `GET` request:
  `https://graph.facebook.com/v22.0/{your-ig-user-id}?fields=business_discovery.
username({target-restaurant-username}){followers_count,media_count,media{caption
,media_url,timestamp,permalink}}` [16]
  This call extracts the target restaurant's current follower count, alongside 
its most recent media posts, captions, and direct URLs.[16] This data can then 
be programmatically parsed to identify promotional keywords (e.g., "discount," 
"offer," "Ramadan Special").[16]
* **Rate Limits and Throttling:** Meta enforces a Business Use Case (BUC) 
rate-limiting framework.[14] This framework assigns a base allocation of exactly
200 requests per hour per authenticated Instagram user account.[14, 16] Rather 
than being shared globally, this limit is isolated to each connected 
account.[14] This means that if an aggregator authenticates ten unique user 
accounts, the platform's aggregate limit scales linearly to 2,000 requests per 
hour.[14]
* **API Constraints and Webhook Optimization:** The BUC limit counts both 
successful and failed requests.[14] It also treats cursor-based pagination calls
as separate requests.[14, 17] Crucially, the Instagram Graph API does not expose
follower lists, user IDs, or private communications.[16] It is also limited to 
public business or creator accounts; standard personal profiles cannot be 
queried.[16, 17] Aggregators must parse the `X-Business-Use-Case-Usage` header 
to monitor utilization dynamically.[14] This header displays the consumption 
percentage (`acc_id_util_pct`) and the rolling reset window 
(`reset_time_duration`) to prevent HTTP 429 blockages.[14]

### The Entertainer, iEAT, and B2B Coupon Platforms

For structured, premium promotional content (such as Buy-One-Get-One-Free 
campaigns), corporate integration programs offer high-integrity legal 
pathways.[18]

* **The Entertainer B2B Solutions:** The Entertainer offers specialized 
corporate integrations to distribute rewards programmatically.[18] Their 
"Embedded & API" model allows third-party platforms to connect directly to their
voucher database.[18] This integration exposes structured, validated promotional
metadata, coordinates, and terms of use directly inside the partner application 
via secured REST APIs or embedded web views.[18]
* **iEAT Coupon Partnerships:** The iEAT platform operates on a similar B2B SDK 
and API model. It requires direct commercial contracting to securely serve 
encrypted, validated merchant coupon codes. These codes are mapped to specific 
point-of-sale (POS) terminal validations, preventing duplicate redemption fraud.
* **My Book Qatar and Urban Point:** My Book Qatar and Urban Point dominate the 
localized merchant voucher space.[19, 20] These platforms utilize co-branded 
loyalty models and B2B SDKs.[20] For example, My Book partners with major 
financial institutions like Doha Bank.[20] When integrated, the application 
requests the first six digits of a user’s Doha Bank credit or debit card.[20] 
This input acts as a decryption key, unlocking the corresponding merchant PIN 
validation interfaces and active discount catalogs programmatically.[20]

### Bank Card Discount Aggregation

Qatari commercial banks—including Qatar National Bank (QNB), Commercial Bank of 
Qatar (CBQ), and Doha Bank—frequently launch proprietary lifestyle campaigns 
offering 10% to 20% discounts or "1-for-1" dining privileges.[21, 22, 23]

These offers are rarely consolidated on a public, structured developer API. 
Instead, they are published dynamically across bank-specific web portals, 
customer PDFs, and mobile banking applications.[20, 23] Aggregating banking 
promotions requires direct B2B partnership negotiations to obtain programmatic 
XML or JSON feeds from each financial marketing department. Alternatively, 
developers can scrape the public-facing banking marketing web pages, subject to 
the contract and cybercrime risks detailed below.

| Channel / Partner | API / SDK Integration Model | Legal / Compliance Baseline 
| Technical Barrier |
| :--- | :--- | :--- | :--- |
| **Instagram Graph API** | REST API via Facebook Login & Business Discovery 
[15, 16] | Compliant with Meta Developer Terms of Service [16] | Low (Throttled 
at 200 requests/hour/user) [14] |
| **The Entertainer** | Embedded B2B API & White-Label SDK [18] | Governed by 
enterprise B2B licensing contract [18] | Medium (Requires commercial API keys) 
[18] |
| **iEAT** | Direct POS-Integrated Voucher API | Governed by merchant 
exploitation agreements | Medium (Requires POS validation logic) |
| **My Book Qatar** | Co-Branded Card BIN Verification (6-Digit Handshake) [20] 
| Restricted to authorized Doha Bank/Mastercard users [20] | High (Requires bank
card validation infrastructure) [20] |

---

## Qatar PDPPL Compliance Architecture

The Personal Data Privacy Protection Law (promulgated via Law No. 13 of 2016) 
regulates all digital processing, storage, extraction, and transfer of personal 
data within Qatar.[24, 25]

### Scope of Application and Regulatory Oversight

The PDPPL applies broadly to any personal data that is electronically processed,
or collected in preparation for digital processing.[24, 26] 

* **Regulatory Administration:** Oversight is managed by the Ministry of 
Communications and Information Technology (MCIT) through the Compliance and Data
Protection Department (CDPD) and the National Cyber Governance and Assurance 
Affairs (NCGAA).[24, 27]
* **Jurisdictional Duality:** Qatar operates a dual data protection regime.[24] 
Aggregators registered on the Qatari mainland must comply with the state-level 
PDPPL, whereas entities registered within the free-zone jurisdiction of the 
Qatar Financial Centre (QFC) are subject to the independent QFC Data Protection 
Regulations.[24]
* **Record of Processing Activities (RoPA):** Under the law, data controllers 
are legally required to maintain a comprehensive RoPA.[27] This ledger must 
document the precise lifecycle of all processed user data, mapping data flows, 
origins, destinations, retention schedules, and classification metrics.[27]

### Consent Management and Individual Rights

Consent is the primary legal basis for data processing under the PDPPL.[26, 27]

* **Explicit Opt-In Mandate:** Aggregators must deploy a validated Consent 
Management Platform (CMP) on all web and mobile interfaces.[27] By default, CMP 
interfaces must be set to opt-out, requiring users to explicitly execute an 
unambiguous action to opt-in before cookies or identifiers are tracked.[27] 
Consent must be as easy to withdraw as it is to grant, requiring accessible 
"opt-out" control panels.[26, 27]
* **Data Subject Rights:** Users maintain legally enforceable rights of access, 
rectification, erasure (the "right to be forgotten"), portability, and the right
to object to automated profiling or direct marketing.[24, 26, 27]
* **Cross-Border Transfers:** Transferring personal data outside Qatar is 
restricted.[24, 25] It is prohibited unless the destination country provides an 
"adequate level of protection" verified by the MCIT, or explicit authorization 
is obtained from the competent state authority.[24, 25]

### Processing Sensitive Personal Data

Under Article 18, special categories of personal data—classified as sensitive 
personal data—include physical or mental health, ethnic origin or race, 
religious beliefs, relationships or marital status, criminal records, and 
children.[24, 26]

Processing sensitive data requires both explicit user consent and written 
approval from the MCIT.[24, 27] Furthermore, processing any data relating to 
minors requires verified parental or legal guardian consent.[28, 29]

### The Anonymisation Exemption

The PDPPL does not apply to data that is processed in a manner that permanently 
prevents the identification of an individual.[24] If a promotion aggregator 
structures its database to process only restaurant metadata and discount 
values—completely stripping out unique user identifiers, IP addresses, and GPS 
coordinates—the dataset falls outside the definition of personal data.[24] This 
"Anonymisation Exemption" allows aggregators to bypass the consent requirements 
and compliance overhead of the PDPPL.[24]

### Legal Exceptions and Statutory Fines

Under Article 18, governmental processing is exempt from standard PDPPL 
provisions for national security, international relations, state financial 
interests, or criminal investigations.[24] However, private aggregators enjoy no
such exemptions.[24] Failure to comply with PDPPL mandates can result in direct 
administrative fines issued by the National Cyber Security Agency (NCSA), 
ranging from 1,000,000 QAR to 5,000,000 QAR.[28]

---

## Copyright, Terms of Service, and Database Exposure

When programmatically extracting and republishing dining offers, aggregators 
face legal exposure across intellectual property, contract, and civil laws.

### The Originality Threshold under Copyright Law No. 7 of 2002

Copyright protection in Qatar is governed by Law No. 7 of 2002 on the Protection
of Copyright and Related Rights.[30, 31]

* **Exclusion of Raw Facts:** Article 4 explicitly dictates that copyright 
protection does not extend to mere ideas, procedures, mathematical concepts, 
principles, or daily news of a purely informative nature.[31] Therefore, basic 
promotional facts (e.g., *"Zaatar W Zeit offers a 15% discount on Wednesdays"*) 
are not copyrightable.[2, 30, 31] Aggregators can legally compile and display 
these facts without author authorization.[30, 31]
* **Database Compilation Protections:** Copyright protection does extend to 
collections of databases if they involve "creative work in the selection and 
arrangement of their subject matter".[31] If an aggregator copies, reproduces, 
or republishes a competitor's structured database, this action violates the 
creator's exclusive exploitation rights.[30, 32]
* **Duration of Protection:** Financial and exploitation rights are protected 
during the author's life and for fifty calendar years after their death.[32] 
Collective, audiovisual, or pseudonymous works are protected for fifty years 
from their first publication.[32]
* **Exemptions for Government Open Data:** Data created and published on various
websites of the agencies of the government of Qatar is automatically protected 
by copyright law.[33] However, under Qatar's Open Data Policy, agencies may 
apply public open licenses that grant a worldwide, royalty-free, non-exclusive, 
irrevocable license to reproduce and share the material for commercial or 
research purposes.[33] This does not apply to third-party data published on 
government websites, which remains subject to its original license.[33]

### Contractual Liability and Terms of Service (ToS)

Under Qatar's Civil Code (Law No. 22 of 2004), website Terms of Service (ToS) 
are treated as legally binding contracts.[30]

* **Breach of Contract:** If an aggregator uses automated scripts, headless 
browsers, or API scrapers on a platform whose ToS explicitly prohibits automated
browsing or data harvesting, the scraping activity constitutes a breach of 
contract.[30] Agreement to these terms is established by accessing the platform,
making the user liable for civil damages.[30]
* **Circumvention of Technological Protection Measures (TPM):** Section 36A of 
the copyright framework prohibits bypassing Technological Protection Measures 
(TPMs)—such as encryption, tokenization, and anti-bot validation.[30] Bypassing 
these barriers to extract data constitutes a statutory violation of copyright 
integrity.[30]

### Legal Remedies for Infringement

Under Law No. 7 of 2002, if a court determines that an aggregator has infringed 
copyright or unauthorized database rights, it may order the following civil 
remedies:

* Granting of immediate injunctions to prohibit further exploitation or display 
of the work.[32]
* Ordering the seizure of infringing copies, data stores, and all hardware or 
equipment used to facilitate the unauthorized reproduction.[32]
* Awarding appropriate financial compensation and indemnification for damages 
suffered by the injured platform.[32]
* Ordering the seizure of all profits directly attributable to the 
infringement.[32]

---

## Cybercrime Prevention Law and Web Scraping Viability

The most critical legal hazard for automated scraping in Qatar is the Cybercrime
Prevention Law (Law No. 14 of 2014).[29, 34, 35]

### Criminal Liability under Law No. 14 of 2014

Law No. 14 of 2014 criminalizes unauthorized access to digital systems, 
databases, and networks, introducing severe penal consequences for data 
harvesting.[29, 34, 35]

* **Article 3 (Unauthorized Access):** Any person who intentionally and 
unlawfully accesses a website, an information system, or an information network 
by any means shall be punished by imprisonment for a term of up to three years, 
a fine of up to 500,000 QAR, or both.[34] If the target system belongs to a 
state authority or institution, the penalties are elevated.[34] In legal 
contexts, utilizing automated scraping bots to access private API endpoints, 
mimicking authenticated merchant sessions, or bypassing authentication protocols
is treated as unauthorized access and system trespass.[30, 34, 36]
* **Article 4 (Data Interception):** This article criminalizes the unauthorized 
capturing, interception, or spying of traffic data or transmission streams.[34] 
Violations carry penalties of up to two years imprisonment and fines of up to 
100,000 QAR.[34] This applies directly to developers sniffing app traffic or 
intercepting API responses.[34]
* **Article 11 (Offensive Credentials):** This article criminalizes the 
unauthorized possession of electronic passwords, data access codes, or 
decryption keys to commit cyber offenses.[37] Sniffing authentication tokens 
(e.g., Talabat's Bearer tokens) or using compromised merchant credentials to 
scrape data is prosecuted under this article.[3, 37]
* **Spreading False Information and Social Values:** Article 6 and Article 8 
penalize the publication of false information or content that violates social 
values via information networks.[34, 35] If a scraper extracts outdated, 
inaccurate promotional data that misleads consumers or harms a restaurant's 
reputation, the operator can face criminal prosecution.[34, 35] This can lead to
up to three years in prison and a fine of up to 100,000 QAR.[34]

### Scraping Viability Analysis

Despite these legal barriers, third-party data firms (such as Actowiz Solutions 
and FoodDataScrape) sell pre-scraped datasets containing historical prices, 
delivery fees, and promotional data for Snoonu, Rafeeq, and Talabat.[38, 39] 
Utilizing these pre-packaged datasets shifts the technical and legal burden of 
scraping away from the aggregator.[38] However, building a proprietary, 
real-time scraping pipeline remains highly unfeasible and legally risky.[30, 34]

To evaluate the feasibility of web scraping across different targets, a 
quantitative Risk Coefficient ($R_C$) is calculated using three variables rated 
on a scale of 1 to 5:
1. Legal Risk ($L$): The level of exposure to criminal prosecution under 
Cybercrime Law No. 14 of 2014 and civil breach of contract claims under Law No. 
22 of 2004.[30, 34]
2. Technical Scraping Barrier ($T$): The complexity of bypassing platform 
defenses, such as Cloudflare, Akamai WAFs, app-only payload encryption, and API 
signature validations.
3. Dynamic Frequency Difficulty ($F$): The requirement for continuous, real-time
extraction due to the highly volatile nature of restaurant promotions and menu 
availability.

The Overall Risk Coefficient ($R_C$) is calculated as follows:

$$R_C = \frac{L + T + F}{3}$$

A score where $R_C \ge 4.0$ indicates an unsustainable, high-risk aggregation 
strategy that is highly susceptible to legal action or technical failures.

```
                             WEB SCRAPING RISK INDEX (Rc)
5.0 ───────────────────────────────────────────────────────────────── Rafeeq 
(5.00)
    │                                                                 Talabat / 
Snoonu (4.67)
4.0 ┼────────────────────────────────────────────────────────────────
    │
3.0 ┼──────────────────────────────────── The Entertainer / My Book (3.00)
    │
2.0 ┼────────────────────────────────────
    │                                     Instagram Graph API (1.67)
1.0 ┴────────────────────────────────────────────────────────────────
    0.0                                                               5.0
```

* **Talabat (Risk Coefficient: 4.67):** High legal exposure due to strict terms 
of service and criminal risk under Law No. 14 of 2014.[30, 34] Technically 
challenging to scrape due to Cloudflare WAF protections, dynamic JSON payload 
tokenization, and anti-scraping blocks.[3, 5] High frequency demands make 
continuous parsing highly unstable.
* **Snoonu (Risk Coefficient: 4.67):** Snoonu's terms of service strictly 
prohibit automated extraction.[30] The platform utilizes heavy application-layer
security, requiring reverse-engineering of mobile app endpoints. This activity 
constitutes unauthorized access under Qatari law.[34]
* **Rafeeq (Risk Coefficient: 5.00):** Rafeeq represents the highest risk 
profile.[12] The serverless AWS infrastructure is protected by dynamic API 
Gateways and automated threat detection, which block abnormal traffic 
patterns.[12] Because Rafeeq lacks a public web interface, scrapers must execute
low-level reverse-engineering of native application header validation 
algorithms, exposing them directly to Article 3 cybercrime charges.[2, 34]
* **Instagram Graph API (Risk Coefficient: 1.67):** High feasibility and low 
legal risk.[16] Querying via the official Business Discovery API bypasses all 
anti-bot mechanisms and fully complies with Meta’s Terms of Service.[15, 16]
* **The Entertainer / My Book (Risk Coefficient: 3.00):** Moderate 
feasibility.[18, 20] These coupon platforms have a low frequency of updates, as 
vouchers are typically valid for months. However, because their business models 
rely on proprietary voucher data, unauthorized scraping of these catalogs can 
trigger copyright database infringement claims and civil contract 
litigation.[30, 32]

---

## Architectural and Legal Strategy for Compliance-First Aggregation

To establish a legally compliant and technically stable promotional aggregator 
in Qatar, developers should avoid unauthorized web scraping of walled 
gardens.[30, 34] Instead, they should deploy a compliance-first, multi-tier 
integration architecture.

```
┌────────────────────────────────────────────────────────┐
│             COMPLIANT AGGREGATION ENGINE               │
└───────────────────────────┬────────────────────────────┘
                            │
         ┌──────────────────┴──────────────────┐
         ▼                                     ▼
 ┌───────────────┐                     ┌───────────────┐
 │ Official APIs │                     │  Partner B2B  │
 └───────┬───────┘                     └───────┬───────┘
         │                                     │
         ├─► Instagram Graph API               ├─► The Entertainer SDK [18]
         │   (Business Discovery) [16]      │
         │                                     ├─► iEAT API Integration
         └─► Bank Promotion Pages              │
             (Public Web DOM Parsing)          ├─► My Book Qatar [20]
                                               │
                                               └─► Merchant Portal
                                                   (Direct Restaurant Feeds)
```

### Tier 1: Social Media Extraction (Organic Promotions)

Deploy an automated ingest engine integrated with Meta’s Instagram Graph 
API.[15, 16]

* **Integration Mechanism:** Establish an array of authenticated Instagram 
Business accounts to scale the Business Use Case (BUC) rate limits.[14, 16] 
* **Data Processing:** Execute programmatic `GET` requests using the Business 
Discovery endpoint to retrieve the captions and media posts of validated 
restaurant profiles in Qatar.[16]
* **Keyword Matching:** Run a Natural Language Processing (NLP) pipeline to 
filter, clean, and categorize promotional offers, mapping them to structured 
merchant profiles in the aggregator database.

### Tier 2: B2B Voucher Licensing (Premium Promotions)

Formally license premium restaurant vouchers and discounts from established 
providers.[18, 20]

* **Integration Mechanism:** Integrate with The Entertainer's "Embedded & API" 
model to ingest standard 1-for-1 discount offers securely.[18] 
* **Cardholder Verification:** For bank-specific campaigns, build a 
BIN-verification system that matches the first six digits of a user's credit or 
debit card against the participating card lists of QNB, CBQ, and Doha Bank.[20, 
22] This approach leverages official marketing partnerships and complies with 
bank data security standards.[20, 21]

### Tier 3: Decentralized Merchant Portal (Self-Service Feed)

To bypass the closed APIs of Talabat, Snoonu, and Rafeeq, establish a 
self-service Merchant Portal.[3]

* **Integration Mechanism:** Develop a web interface where Qatari restaurant 
owners can log in, verify their ownership, and manually publish their active 
promotions, in-store discounts, and direct delivery codes.
* **Value Proposition:** This self-service model bypasses delivery platform 
middleware, provides merchants with direct visibility on the aggregator, and 
avoids the legal risks of unauthorized web scraping under Law No. 14 of 
2014.[30, 34]

### PDPPL Exemption and Data Security Strategy

To operate with minimal compliance overhead, the aggregator database must be 
architected for complete anonymity.[24]

* **Data Minimization:** Under PDPPL Guidelines, if a system processes only 
factual merchant promotions and does not collect or store user personal data, it
is exempt from consent requirements.[24, 27]
* **Local Hosting Compliance:** If the platform eventually introduces user 
accounts (for saving favorite deals or geolocating offers), all personal data 
must be stored locally on secure cloud infrastructure within Qatar.[24, 25] This
ensures compliance with cross-border data transfer laws.[24, 25]
* **Consent Infrastructure:** The platform must implement an NCSA-compliant 
consent management platform (CMP) to capture explicit opt-in consent for any 
tracking cookies, in line with Law No. 13 of 2016.[27, 28]

---

1. Explore Best Food Delivery Apps in Dubai - Dev Technosys UAE, 
(https://devtechnosys.ae/blog/best-food-delivery-apps-in-dubai/)
2. Rafeeq: Food Delivery in Qatar - Apps on Google Play, 
(https://play.google.com/store/apps/details?id=com.gorafeeq.qatar)
3. Promotions-API | How to Integrate - Talabat Developer Portal, 
(https://developer.talabat.com/en/documentation/promotions-api-how-to-integrate)
4. Documentation - Talabat POS Integration, 
(https://integration.talabat.com/en/documentation)
5. Partner API - Talabat Developer Portal, 
(https://developer.talabat.com/api-specifications)
6. Introduction - Talabat Developer Portal, 
(https://developer.talabat.com/en/documentation/introduction)
7. Talabat Developer Portal, (https://developer.talabat.com/)
8. Snoonu: Become A Partner | Fastest Food Delivery & Online Shopping in Qatar, 
(https://partner.snoonu.com/)
9. By Snoonu: S-Cloud — Launch Your Own Super-App, (https://cloud.snoonu.com/)
10. Snoonu Portal - Apps on Google Play, 
(https://play.google.com/store/apps/details?id=com.snoonu.merchantportal)
11. Snoonu drives customer loyalty and repeat orders through a gamified shopping
experience, 
(https://www.braze.com/customers/snoonu-drives-customer-loyalty-and-repeat-order
s)
12. DevOps Engineer (AWS & Automation) at Rafeeq | Wantapply.com, 
(https://wantapply.com/devops-engineer-aws-automation-at-rafeeq)
13. On-Demand Delivery Software in Qatar | White-Label Multi-Service Delivery 
Platform - Saaztro, (https://www.saaztro.co/qatar/on-demand-delivery-software)
14. Instagram Graph API: Complete Developer Guide for 2026 - Elfsight, 
(https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026
/)
15. Instagram API in 2026: every option, free or paid, explained - Zernio, 
(https://zernio.com/blog/instagram-api)
16. Instagram API Follower Count in 2026: Official Graph API Guide - KeyAPI, 
(https://www.keyapi.ai/blog/instagram-api-follower-count/)
17. Instagram Graph API: The Latest Features for Businesses - NEKLO, 
(https://neklo.com/blog/neklo-releases-new-magento-extension-for-instagram-feed)
18. Business Partner, (https://business.theentertainerme.com/)
19. Top Mobile Apps Ranking in Qatar (2026) Most Used & No.1 Apps - Digixvalley,
(https://digixvalley.com/app-development/top-mobile-apps-ranking-in-qatar/)
20. Mastercard My Book Qatar - Doha Bank, 
(https://qa.dohabank.com/personal/cards/debit-card-products/world-elite/my-book-
qatar-app/)
21. Qatar Airways Privilege Club Credit Card by Doha Bank, 
(https://qa.dohabank.com/personal/cards/credit-card-products/qatar-airways-privi
lege-club-credit-card-by-doha-bank/)
22. CBQ Vs QNB - Which is better : r/qatar - Reddit, 
(https://www.reddit.com/r/qatar/comments/1kajo71/cbq_vs_qnb_which_is_better/)
23. Credit Card Offers - Doha Bank Qatar, 
(https://qa.dohabank.com/personal/cards/credit-card-offers/)
24. Data Protection & Privacy 2026 - Comparisons | Global Practice Guides | 
Chambers and Partners, 
(https://practiceguides.chambers.com/practice-guides/comparison/1129/18517/29027
-29028-29029-29030-29031)
25. Qatar Personal Data Privacy Protection Law - Centraleyes, 
(https://www.centraleyes.com/qatar-personal-data-privacy-protection-law/)
26. Guide to Qatar's Personal Data Privacy Protection Law (PDPPL), 
(https://business.privacybee.com/resource-center/guide-to-qatars-personal-data-p
rivacy-protection-law-pdpl/)
27. Qatar Personal Data Privacy Protection Law (PDPPL) Compliance - ImmuniWeb, 
(https://www.immuniweb.com/compliance/qatar-personal-data-privacy-protection-law
-pdppl-compliance/)
28. A Quick Guide to Law No. 13 of 2016 on Protecting Personal Data Privacy 
(PDPL), (https://www.youtube.com/watch?v=xuQEeOpT-3U)
29. Best Cyber Law, Data Privacy and Data Protection Lawyers in Al Wakrah - 
Lawzana, 
(https://lawzana.com/cyber-law-data-privacy-and-data-protection-lawyers/al-wakra
h)
30. The legal landscape of web scraping | Asia IP, 
(https://asiaiplaw.com/section/in-depth/the-legal-landscape-of-web-scraping)
31. Law No. 7 of 2002 on the Protection of Copyright and Related Rights, Qatar, 
WIPO Lex, (https://www.wipo.int/wipolex/en/legislation/details/3567)
32. Law No. 7 of 2002 on the Protection of Copyright and Neighbouring Rights, 
(https://www.almeezan.qa/LawView.aspx?LawID=2637&language=en&opt)
33. Open Data Licensing Policy, (https://www.data.gov.qa/pages/license/)
34. Law No. (14) of 2014 Promulgating the Cybercrime Prevention Law, 
(https://www.almeezan.qa/EnglishLaws/142014.pdf)
35. Cyber Law at Qatar - Law Gratis, 
(https://www.lawgratis.com/blog-detail/cyber-law-at-qatar-1)
36. Why Hackers Win: Power and Disruption in the Network Society 9780520971653, 
(https://dokumen.pub/why-hackers-win-power-and-disruption-in-the-network-society
-9780520971653.html)
37. Differences in Students' Attitudes Towards Jordanian and Qatari Cybercrime 
Laws - Scholars Middle East Publishers, 
(https://saudijournals.com/media/articles/SIJLCJ_85_99-104.pdf)
38. Snoonu Qatar Item, Price & Review Datasets – Real-Time Grocery Data - 
Actowiz Solutions, 
(https://www.actowizsolutions.com/datasets/details/snoonu-qatar-grocery-dataset)
39. Quick Commerce Data Scraping API - Extract API for Q, 
(https://www.fooddatascrape.com/quick-commerce-data-scraping-api.php)


Discovered Sources:
  [0] Comprehensive Legal and Technical Analysis of Restaurant Promotion 
Aggregation in Qatar
  [1] Promotions-API | How to Integrate - Talabat Developer Portal
      https://developer.talabat.com/en/documentation/promotions-api-how-to-integ
rate
  [2] Partner API - Talabat Developer Portal
      https://developer.talabat.com/api-specifications
  [3] The legal landscape of web scraping | Asia IP
      https://asiaiplaw.com/section/in-depth/the-legal-landscape-of-web-scraping
  [4] Business Partner
      https://business.theentertainerme.com/
  [5] Data Protection & Privacy 2026 - Comparisons | Global Practice Guides | 
Chambers and Partners
      https://practiceguides.chambers.com/practice-guides/comparison/1129/18517/
29027-29028-29029-29030-29031
  [6] Qatar Personal Data Privacy Protection Law - Centraleyes
      https://www.centraleyes.com/qatar-personal-data-privacy-protection-law/
  [7] Instagram Graph API: Complete Developer Guide for 2026 - Elfsight
      https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for
-2026/
  [8] Instagram API Follower Count in 2026: Official Graph API Guide - KeyAPI
      https://www.keyapi.ai/blog/instagram-api-follower-count/
  [9] Quick Commerce Data Scraping API - Extract API for Q
      https://www.fooddatascrape.com/quick-commerce-data-scraping-api.php
  [10] Snoonu Qatar Item, Price & Review Datasets – Real-Time Grocery Data - 
Actowiz Solutions
      https://www.actowizsolutions.com/datasets/details/snoonu-qatar-grocery-dat
aset
  [11] Mastercard My Book Qatar - Doha Bank
      https://qa.dohabank.com/personal/cards/debit-card-products/world-elite/my-
book-qatar-app/
  [12] Introduction - Talabat Developer Portal
      https://developer.talabat.com/en/documentation/introduction
  [13] Talabat Developer Portal
      https://developer.talabat.com/
  [14] Documentation - Talabat POS Integration
      https://integration.talabat.com/en/documentation
  [15] Instagram API in 2026: every option, free or paid, explained - Zernio
      https://zernio.com/blog/instagram-api
  [16] Instagram Graph API: The Latest Features for Businesses - NEKLO
      https://neklo.com/blog/neklo-releases-new-magento-extension-for-instagram-
feed
  [17] Guide to Qatar's Personal Data Privacy Protection Law (PDPPL)
      https://business.privacybee.com/resource-center/guide-to-qatars-personal-d
ata-privacy-protection-law-pdpl/
  [18] Qatar Personal Data Privacy Protection Law (PDPPL) Compliance - ImmuniWeb
      https://www.immuniweb.com/compliance/qatar-personal-data-privacy-protectio
n-law-pdppl-compliance/
  [19] Law No. 7 of 2002 on the Protection of Copyright and Neighbouring Rights
      https://www.almeezan.qa/LawView.aspx?LawID=2637&language=en&opt
  [20] Law No. (14) of 2014 Promulgating the Cybercrime Prevention Law
      https://www.almeezan.qa/EnglishLaws/142014.pdf
  [21] Cyber Law at Qatar - Law Gratis
      https://www.lawgratis.com/blog-detail/cyber-law-at-qatar-1
  [22] Differences in Students' Attitudes Towards Jordanian and Qatari 
Cybercrime Laws - Scholars Middle East Publishers
      https://saudijournals.com/media/articles/SIJLCJ_85_99-104.pdf
  [23] Law No. 7 of 2002 on the Protection of Copyright and Related Rights, 
Qatar, WIPO Lex
      https://www.wipo.int/wipolex/en/legislation/details/3567
  [24] Open Data Licensing Policy
      https://www.data.gov.qa/pages/license/
  [25] Snoonu: Become A Partner | Fastest Food Delivery & Online Shopping in 
Qatar
      https://partner.snoonu.com/
  [26] By Snoonu: S-Cloud — Launch Your Own Super-App
      https://cloud.snoonu.com/
  [27] Snoonu Portal - Apps on Google Play
      https://play.google.com/store/apps/details?id=com.snoonu.merchantportal
  [28] Credit Card Offers - Doha Bank Qatar
      https://qa.dohabank.com/personal/cards/credit-card-offers/
  [29] DevOps Engineer (AWS & Automation) at Rafeeq | Wantapply.com
      https://wantapply.com/devops-engineer-aws-automation-at-rafeeq
  [30] Explore Best Food Delivery Apps in Dubai - Dev Technosys UAE
      https://devtechnosys.ae/blog/best-food-delivery-apps-in-dubai/
  [31] Rafeeq: Food Delivery in Qatar - Apps on Google Play
      https://play.google.com/store/apps/details?id=com.gorafeeq.qatar
  [32] Snoonu drives customer loyalty and repeat orders through a gamified 
shopping experience
      https://www.braze.com/customers/snoonu-drives-customer-loyalty-and-repeat-
orders
  [33] On-Demand Delivery Software in Qatar | White-Label Multi-Service Delivery
Platform - Saaztro
      https://www.saaztro.co/qatar/on-demand-delivery-software
  [34] Best Cyber Law, Data Privacy and Data Protection Lawyers in Al Wakrah - 
Lawzana
      https://lawzana.com/cyber-law-data-privacy-and-data-protection-lawyers/al-
wakrah
  [35] A Quick Guide to Law No. 13 of 2016 on Protecting Personal Data Privacy 
(PDPL)
      https://www.youtube.com/watch?v=xuQEeOpT-3U
  [36] Top Mobile Apps Ranking in Qatar (2026) Most Used & No.1 Apps - 
Digixvalley
      https://digixvalley.com/app-development/top-mobile-apps-ranking-in-qatar/
  [37] CBQ Vs QNB - Which is better : r/qatar - Reddit
      https://www.reddit.com/r/qatar/comments/1kajo71/cbq_vs_qnb_which_is_better
/
  [38] Qatar Airways Privilege Club Credit Card by Doha Bank
      https://qa.dohabank.com/personal/cards/credit-card-products/qatar-airways-
privilege-club-credit-card-by-doha-bank/
  [39] Why Hackers Win: Power and Disruption in the Network Society 
9780520971653
      https://dokumen.pub/why-hackers-win-power-and-disruption-in-the-network-so
ciety-9780520971653.html
  [40] Business in Qatar – Find Professionals | MzadQatar
      https://mzadqatar.com/en/business-services/services-offered?page=6
  [41] Various Projects & Services Available | Mzad Qatar
      https://mzadqatar.com/en/business-services/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-
%D9%85%D8%B9%D8%B1%D9%88%D8%B6%D8%A9/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A7%D8%AE
%D8%B1%D9%8A?page=4
  [42] Simple Steps to Develop An App Like Rafeeq in 2026 - Dev Technosys UAE
      https://devtechnosys.ae/blog/develop-an-app-like-rafeeq/
  [43] Urgent! Websites jobs in Doha - 77 current vacancies | Jobsora
      https://ae.jobsora.com/jobs-websites-doha-qatar
  [44] Terms of use - Qatar Digital Library
      https://www.qdl.qa/en/terms-use
  [45] Mazzraty Homedelivery - App Store - Apple
      https://apps.apple.com/qa/app/mazzraty-homedelivery/id6755688295
  [46] The SpeedyKart - App Store - Apple
      https://apps.apple.com/in/app/the-speedykart/id6523429465
  [47] An intelligent marketing platform with influencer classification in 
social networking services - SKKU
      https://iotlab.skku.edu/publications/international-journal/Elsevier-KBS-SN
S-Influencer-Classification-2025.pdf
  [48] index all classes all packages - restfb 3.15.0 javadoc
      https://javadoc.io/doc/com.restfb/restfb/3.15.0/index-all.html
  [49] E-Commerce Guidelines
      https://ecommerce.gov.qa/wp-content/uploads/2019/07/5.-eCommerce-Guidlines
-Terms-Conditions.pdf
  [50] How to Automate Your Doha Business | Workflow Automation Guide - Autonoly
      https://www.autonoly.com/locations/doha/workflow-automation
  [51] Gourmet Food & Beverage Data Analysis in Qatar - Actowiz Metrics
      https://www.actowizmetrics.com/gourmet-food-beverage-data-analysis-qatar.p
hp
  [52] MobileAppDaily Sitemap – Explore All Pages Now!
      https://www.mobileappdaily.com/sitemap
  [53] Cybercrime & Cybersecurity in the Middle East: Stay Secure - Lawrbit
      https://www.lawrbit.com/global/cybercrime-and-cybersecurity-navigating-the
-middle-eastern-landscape/
  [54] Compare Credit Cards in Qatar - Doha - YallaCompare
      https://yallacompare.com/qat/en/credit-cards/

Run 'nlm research import ab714aa8-ea30-47aa-98ec-85722c591a3c <task-id>' to 
import sources.
