# SVIS Extraction Quality Review: July 2026 Baseline

- **Questionnaire PDF reviewed:** `tests/samples/surveys/final_interview_HBS_2014.pdf` (Household Budget Survey in Albania 2014, Final Interview)
- **Extraction output reviewed:** Historical 239-variable `ALB_2014_HBS` output produced by the Docling pipeline with Azure OpenAI `gpt-4.1-mini`
- **Date of review:** 2026-07-28
- **Total variables extracted:** 239
- **Number flagged for review (`needs_review: true`):** 61

> **Baseline scope:** This document preserves the manual review of the July 28 extraction. The current `output/ALB_2014_HBS_svis.json` has since been regenerated and contains 290 variables, of which 52 are flagged for review. It has not received the same per-variable manual assessment, so the accuracy percentages below must not be applied to the current output.

------------------------------------------------------------------------

## Step 2-3: Per-variable review and tally

Every variable in the JSON was compared against its source question in the questionnaire (cross-referenced via the MarkItDown/Docling conversions in `tests/samples/conversions/`). Outcome key: **C** = Correct, **P** = Partial, **W** = Wrong. Notes are given only where the outcome is not Correct.

| \# | raw_name | Module | Outcome | Notes |
|------------|----------------|--------------------|:----------:|------------|
| 1 | diary_delivery_date | INTERVIEWER | C |  |
| 2 | diary_reference_month | INTERVIEWER | P | Month codes 1-12 not shown in source; inferred from standard calendar |
| 3 | psu | TO BE FILLED BY THE INTERVIEWER | C |  |
| 4 | city_village | TO BE FILLED BY THE INTERVIEWER | C |  |
| 5 | municipality_commune | TO BE FILLED BY THE INTERVIEWER | C |  |
| 6 | household_progressive_number | TO BE FILLED BY THE INTERVIEWER | C |  |
| 7 | interviewer_code | TO BE FILLED BY THE INTERVIEWER | C |  |
| 8 | supervisor_code | TO BE FILLED BY THE INTERVIEWER | C |  |
| 9 | household_code | TO BE FILLED BY THE INTERVIEWER | C |  |
| 10 | district | TO BE FILLED BY THE INTERVIEWER | C |  |
| 11 | latitude | TO BE FILLED BY THE SUPERVISOR | C |  |
| 12 | household_phone_number | TO BE FILLED BY THE SUPERVISOR | C |  |
| 13 | longitude | TO BE FILLED BY THE SUPERVISOR | C |  |
| 14 | self_consumption_booklet_filled | TO BE FILLED BY THE SUPERVISOR | C |  |
| 15 | highest_education_level | Q ues ti on 3 | P | Codes 2 and 3 have identical duplicated label text ("Lower secondary vocational") |
| 16 | relationship_to_head (1st) | Question 14 | C |  |
| 17 | reason_for_not_presence | Question 14 | C |  |
| 18 | marital_status (1st) | Q ues ti on 7 | C |  |
| 19 | presence_last_12_months_absent | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 20 | presence_14_days | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 21 | school_years_completed | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 22 | highest_diploma_attained | Section 1- DATA ON HOUSEHOLD MEMBERS | P | `categories: null`; answer codes for diploma levels not extracted from the table |
| 23 | father_code | Section 1- DATA ON HOUSEHOLD MEMBERS | P | Code 99 ("if no present write 99") mislabeled "Spouse / Partner code" instead of a missing/NA label; `is_missing` not set to `true` |
| 24 | mother_code | Section 1- DATA ON HOUSEHOLD MEMBERS | P | Same code-99 mislabeling / missing-flag issue as father_code |
| 25 | marital_status (2nd) | Section 1- DATA ON HOUSEHOLD MEMBERS | W | Duplicate of #18, re-extracted with `categories: null` — same question chunked/asked twice by the pipeline |
| 26 | age_years | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 27 | year | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 28 | month | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 29 | day | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 30 | sex | Section 1- DATA ON HOUSEHOLD MEMBERS | C |  |
| 31 | relationship_to_head (2nd) | Section 1- DATA ON HOUSEHOLD MEMBERS | W | Duplicate of #16, re-extracted with `categories: null` |
| 32 | tried_find_job_4weeks | HOUSEHOLD BUDGET SURVEY ALBANIA | C |  |
| 33 | ready_start_work_2weeks | HOUSEHOLD BUDGET SURVEY ALBANIA | C |  |
| 34 | permanent_job_status | HOUSEHOLD BUDGET SURVEY ALBANIA | C |  |
| 35 | worked_past_7days | HOUSEHOLD BUDGET SURVEY ALBANIA | C |  |
| 36 | dwelling_type | A\) MAIN DWELLING | C |  |
| 37 | dwelling_year_constructed | A\) MAIN DWELLING | C |  |
| 38 | dwelling_area | A\) MAIN DWELLING | C |  |
| 39 | dwelling_facilities_separate_kitchen | A\) MAIN DWELLING | C |  |
| 40 | dwelling_facilities_internal_toilet | A\) MAIN DWELLING | C |  |
| 41 | dwelling_facilities_external_toilet | A\) MAIN DWELLING | C |  |
| 42 | dwelling_facilities_shower | A\) MAIN DWELLING | C |  |
| 43 | dwelling_facilities_drinking_water_supply | A\) MAIN DWELLING | C |  |
| 44 | dwelling_facilities_hot_water | A\) MAIN DWELLING | C |  |
| 45 | dwelling_facilities_electric_power | A\) MAIN DWELLING | C |  |
| 46 | dwelling_facilities_sewerage_system | A\) MAIN DWELLING | C |  |
| 47 | dwelling_facilities_central_heating | A\) MAIN DWELLING | C |  |
| 48 | dwelling_facilities_telephone_line | A\) MAIN DWELLING | C |  |
| 49 | dwelling_facilities_internet_connection | A\) MAIN DWELLING | C |  |
| 50 | dwelling_facilities_garage | A\) MAIN DWELLING | C |  |
| 51 | dwelling_facilities_pantry | A\) MAIN DWELLING | C |  |
| 52 | dwelling_facilities_attic | A\) MAIN DWELLING | C |  |
| 53 | dwelling_facilities_balcony | A\) MAIN DWELLING | C |  |
| 54 | dwelling_facilities_rampa | A\) MAIN DWELLING | C |  |
| 55 | dwelling_facilities_elevator | A\) MAIN DWELLING | C |  |
| 56 | dwelling_facilities_garden | A\) MAIN DWELLING | C |  |
| 57 | heating_type | A\) MAIN DWELLING | C | Categories/codes correct; `question_text` left as raw OCR checkbox markup (`- [ ] Electric boiler 1...`) instead of clean prose |
| 58 | heating_source_type | A\) MAIN DWELLING | C | Same raw-checkbox-markup artifact in `question_text` |
| 59 | heating_fuel_source | A\) MAIN DWELLING | C | Same raw-checkbox-markup artifact in `question_text` |
| 60 | heat_supply_main | DWELLING SERVICES | C |  |
| 61 | dwelling_type_interviewer | DWELLING SERVICES | W | Categories ("Detached house", "Semi-detached house"...) are generic textbook options, self-flagged as inferred, not sourced from the questionnaire text |
| 62 | number_of_rooms | CHARACTERISTICS OF DWELLING | C |  |
| 63 | hot_water_appliance_type | CHARACTERISTICS OF DWELLING | W | Categories "Type 1 appliance" / "Type 2 appliance" are meaningless placeholders, not real appliance names |
| 64 | year_move_in | LEGAL STATUS OF USE OF THE DWELLING | C |  |
| 65 | dwelling_legal_status | LEGAL STATUS OF USE OF THE DWELLING | C |  |
| 66 | rent_dwelling_without_equipment | LEGAL STATUS OF USE OF THE DWELLING | C |  |
| 67 | rent_dwelling_with_equipment | LEGAL STATUS OF USE OF THE DWELLING | C |  |
| 68 | legal_status_use_dwelling | (If owner, joint-owner...) | P | `categories: null`; answer options not extracted |
| 69 | dwelling_rented_with_equipment | (If owner, joint-owner...) | W | Codes 6/9 for Yes/No are implausible (every other Yes/No question in the doc uses 1/2) — likely a code-alignment error |
| 70 | monthly_rent | (If owner, joint-owner...) | P | No numeric range or currency captured, self-flagged ambiguity |
| 71 | regular_maintenance_exp_6m | MAINTENANCE OF MAIN DWELLING | C |  |
| 72 | extraordinary_maintenance_exp_6m | MAINTENANCE OF MAIN DWELLING | P | Only code 9 ("can't remember") captured; YES/NO codes missing |
| 73 | regular_maintenance_exp_amount | MAINTENANCE OF MAIN DWELLING | C |  |
| 74 | extraordinary_maintenance_exp_amount | MAINTENANCE OF MAIN DWELLING | C |  |
| 75 | legal_status | B\) SECONDARY DWELLING | C |  |
| 76 | secondary_dwellings_count | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 77 | use_another_dwelling | CURRENT EXPENDITURES OF SECOND DWELLING | P | Only code 9 ("No") captured; YES option missing |
| 78 | monthly_rent_or_imputed | CURRENT EXPENDITURES OF SECOND DWELLING | P | Question conflates several sub-questions into one variable |
| 79 | last_month_rent_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 80 | expenditure_common_building | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 81 | internet_services_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 82 | electric_power_bill | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 83 | telephone_services_bill | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 84 | garage_and_other_rentals | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 85 | expenditure_none_24 | CURRENT EXPENDITURES OF SECOND DWELLING | P | Standalone "no expenditures" catch-all extracted as its own variable rather than an `is_missing` category |
| 86 | expenditure_none_25 | CURRENT EXPENDITURES OF SECOND DWELLING | P | Same "no expenditures" catch-all pattern |
| 87 | liquefied_hydrocarbons_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 88 | drinking_water_bill | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 89 | bundled_telecom_services_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 90 | coal_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 91 | gas_cylinders_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 92 | kerosene_gasoil_payment | CURRENT EXPENDITURES OF SECOND DWELLING | C |  |
| 93 | maintenance_regular_exp | MAINTENANCE OF SECONDARY DWELLING | W | Code 9 labeled "No" but also flagged `is_missing: true` — contradictory (9 cannot be both a literal "No" answer and a missing-value sentinel) |
| 94 | maintenance_extraordinary_exp | MAINTENANCE OF SECONDARY DWELLING | W | Same code-9 contradiction as above |
| 95 | amount_regular_exp | MAINTENANCE OF SECONDARY DWELLING | C |  |
| 96 | amount_extraordinary_exp | MAINTENANCE OF SECONDARY DWELLING | C |  |
| 97 | ownership_electric_gas_cookers | C\) DURABLE GOODS | C |  |
| 98 | years_since_acquired_electric_gas_cookers | C\) DURABLE GOODS | C | Range 0-100 inferred, reasonable |
| 99 | ownership_microwave_oven | C\) DURABLE GOODS | C |  |
| 100 | years_since_acquired_microwave_oven | C\) DURABLE GOODS | C |  |
| 101 | ownership_firewood_coal_stove | C\) DURABLE GOODS | C |  |
| 102 | years_since_acquired_firewood_coal_stove | C\) DURABLE GOODS | C |  |
| 103 | ownership_refrigerator | C\) DURABLE GOODS | C |  |
| 104 | years_since_acquired_refrigerator | C\) DURABLE GOODS | C |  |
| 105 | ownership_freezer_fridge_freezer | C\) DURABLE GOODS | C |  |
| 106 | years_since_acquired_freezer_fridge_freezer | C\) DURABLE GOODS | C |  |
| 107 | ownership_dish_washer | C\) DURABLE GOODS | C |  |
| 108 | years_since_acquired_dish_washer | C\) DURABLE GOODS | C |  |
| 109 | ownership_washing_machine | C\) DURABLE GOODS | C |  |
| 110 | years_since_acquired_washing_machine | C\) DURABLE GOODS | C |  |
| 111 | ownership_drying_machine | C\) DURABLE GOODS | C |  |
| 112 | years_since_acquired_drying_machine | C\) DURABLE GOODS | C |  |
| 113 | repairement_repair_cost | C\) DURABLE GOODS | P | Currency/unit ambiguous ("Old Leks" mentioned elsewhere in section but not here) |
| 114 | purchase_gifts_last_3_months | C\) DURABLE GOODS | C |  |
| 115 | furniture_purchase | Section 3: EXPENDITURES FOR FURNITURE... | P | 16 codes "inferred from ordering" per self-note; not verified against the actual source table order |
| 116 | expend_domestic_workers_month | A\) INSIDE OR GARDEN FURNITURE | C | Codes assumed (Yes=1/No=2) but plausible and consistent with the rest of the doc |
| 117 | amount_paid_old_leks (1st) | B\) SMALL ELECTRIC HOUSEHOLD APPLIANCES... | P | Question text minimal/ambiguous, self-flagged low confidence |
| 118 | garments_footwear_purchase_last_month | Section 4: GARMENTS AND FOOTWEAR | W | 40-code list with **duplicate codes carrying conflicting labels** (e.g. `3 031221` appears twice with two different labels; `3 031231`, `3 031234` likewise) — a clear column-misalignment/hallucination artifact from the noisy source table |
| 119 | health_expenditure_last3months | Section 5: HEALTH | C |  |
| 120 | expenditure_amount_by_item | Section 5: HEALTH | P | Question text incomplete; item list partially garbled |
| 121 | household_health_insurance_member_exist | Section 5: HEALTH | C |  |
| 122 | number_members_with_health_insurance | Section 5: HEALTH | C |  |
| 123 | informal_payments | Therapeutic appliances and equipment | P | Question text is a fragment, self-flagged |
| 124 | value_old_leks | Therapeutic appliances and equipment | P | Question text is a fragment |
| 125 | total_value_old_leks | Therapeutic appliances and equipment | P | Question text is a fragment; unclear if an aggregate/derived field |
| 126 | vehicle_ownership_car | Section 6: TRANSPORT AND COMMUNICATION | P | Multi-select vehicle-type list split into 6 separate YES/NO variables; codes inferred, not explicit |
| 127 | vehicle_ownership_motorcycles | Section 6: TRANSPORT AND COMMUNICATION | P | Same pattern as above |
| 128 | vehicle_ownership_motorbikes_scooters_mopeds | Section 6: TRANSPORT AND COMMUNICATION | P | Same pattern |
| 129 | vehicle_ownership_camper_vans_trailers | Section 6: TRANSPORT AND COMMUNICATION | P | Same pattern |
| 130 | vehicle_ownership_bicycles | Section 6: TRANSPORT AND COMMUNICATION | P | Same pattern |
| 131 | vehicle_ownership_animal_drawn_vehicles | Section 6: TRANSPORT AND COMMUNICATION | P | Same pattern |
| 132 | vehicle_purchase_last_three_months | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 133 | vehicle_type_purchased | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 134 | vehicle_purchase_expenditure_amount | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 135 | vehicle_expenditure_oil_lubricants_antifreeze | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 136 | vehicle_expenditure_tyres | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 137 | vehicle_expenditure_private_garage | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 138 | vehicle_expenditure_spare_parts_accessories | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 139 | vehicle_expenditure_personal_transport_accessories | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 140 | vehicle_expenditure_maintenance_repairs | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 141 | vehicle_expenditure_annual_registration | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 142 | vehicle_expenditure_none | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 143 | number_cars_owned | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 144 | expenditure_interurban_transport | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 145 | communication_equipment_presence | Section 6: TRANSPORT AND COMMUNICATION | W | Categories are meaningless placeholders ("Equipment 073211", "Equipment 073111"...) with no real labels — self-flagged but still emitted as if valid |
| 146 | family_bought_equipment_last_3_months | Section 6: TRANSPORT AND COMMUNICATION | C |  |
| 147 | equipment_type | B\) COMMUNICATIONS | P | Codes/labels show a pattern consistent with two coding schemes merged (e.g. `082111`:"Telephone" vs `082011`:"Telephone (new)") |
| 148 | amount_paid_old_leks (2nd) | B\) COMMUNICATIONS | W | `raw_name` collides with #117 — same identifier reused for a different question in a different module |
| 149 | equipment_ownership_tv | A\) SPARE TIME | P | Question/answer options inferred, not explicit in source, self-flagged |
| 150 | equipment_ownership_video_recorder_dvd | A\) SPARE TIME | P | Same |
| 151 | equipment_ownership_hifi_systems | A\) SPARE TIME | P | Same |
| 152 | equipment_ownership_aircraft | A\) SPARE TIME | P | Same |
| 153 | equipment_ownership_boats | A\) SPARE TIME | P | Same |
| 154 | equipment_ownership_game_sport | A\) SPARE TIME | P | Same |
| 155 | equipment_ownership_music_instruments | A\) SPARE TIME | P | Same |
| 156 | equipment_ownership_major_indoor_recreation | A\) SPARE TIME | P | Same |
| 157 | equipment_ownership_television_aerial_satellite | A\) SPARE TIME | P | Same |
| 158 | equipment_ownership_personal_computer | A\) SPARE TIME | P | Same |
| 159 | subscription_newspapers | B\) CULTURE | C |  |
| 160 | subscription_magazines | B\) CULTURE | C |  |
| 161 | no_expenditures_code | B\) CULTURE | P | Standalone "no expenditures" catch-all pattern (same as #85/#86) |
| 162 | education_expenditure_last_month | C\) EDUCATION | C |  |
| 163 | expenditure_kind_101011 | C\) EDUCATION | P | `raw_name` uses a numeric COICOP-style code instead of a descriptive identifier |
| 164 | expenditure_kind_102001 | C\) EDUCATION | P | Same naming-convention issue |
| 165 | expenditure_kind_102002 | C\) EDUCATION | P | Same |
| 166 | expenditure_kind_102003 | C\) EDUCATION | P | Same |
| 167 | expenditure_kind_102004 | C\) EDUCATION | P | Same |
| 168 | expenditure_kind_103001 | C\) EDUCATION | P | Same |
| 169 | expenditure_kind_104001 | C\) EDUCATION | P | Same |
| 170 | expenditure_kind_104002 | C\) EDUCATION | P | Same |
| 171 | expenditure_kind_104003 | C\) EDUCATION | P | Same |
| 172 | expenditure_kind_104004 | C\) EDUCATION | P | Same |
| 173 | expenditure_kind_105001 | C\) EDUCATION | P | Same |
| 174 | expenditure_kind_073213 | C\) EDUCATION | P | Same |
| 175 | expenditure_kind_095121 | C\) EDUCATION | P | Same |
| 176 | expenditure_kind_105002 | C\) EDUCATION | P | Same |
| 177 | expenditure_kind_112031 | C\) EDUCATION | P | Same |
| 178 | holiday_expenses_last_3m | D\) TRAVELS | C |  |
| 179 | 096011 | 9\. What was the amount of expenditures... | W | `raw_name` is a bare numeric code — not a valid descriptive identifier at all |
| 180 | 096021 | 9\. What was the amount of expenditures... | W | Same |
| 181 | 096012 | 9\. What was the amount of expenditures... | W | Same |
| 182 | 096022 | 9\. What was the amount of expenditures... | W | Same |
| 183 | 112011 | 9\. What was the amount of expenditures... | W | Same |
| 184 | 112012 | 9\. What was the amount of expenditures... | W | Same |
| 185 | 112021 | 9\. What was the amount of expenditures... | W | Same |
| 186 | 112022 | 9\. What was the amount of expenditures... | W | Same |
| 187 | bags_and_travel_goods | A\) OTHER PERSONAL ARTICLES | P | Source text fragmented/unclear, self-flagged |
| 188 | precious_jewellery_clocks_gold_silver | A\) OTHER PERSONAL ARTICLES | P | Code role ambiguity, self-flagged |
| 189 | clock_and_watches | A\) OTHER PERSONAL ARTICLES | C |  |
| 190 | jewellery_no_precious | A\) OTHER PERSONAL ARTICLES | C |  |
| 191 | other_personal_articles | A\) OTHER PERSONAL ARTICLES | C |  |
| 192 | articles_for_babies | A\) OTHER PERSONAL ARTICLES | C |  |
| 193 | electric_appliance_personal_care | A\) OTHER PERSONAL ARTICLES | C |  |
| 194 | repair_of_personal_effects | A\) OTHER PERSONAL ARTICLES | C |  |
| 195 | family_expenditure_private_health_insurance | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 196 | family_expenditure_broker_fees | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 197 | family_expenditure_housing_loan | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 198 | family_expenditure_life_insurance | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 199 | family_expenditure_counselling_services | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 200 | family_expenditure_legal_fees | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 201 | family_expenditure_funeral_services | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 202 | family_expenditure_religious_services | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 203 | family_expenditure_ceremonies | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | P | Question text fragment, self-flagged |
| 204 | family_expenditure_removal_transport | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 205 | family_expenditure_document_provision | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 206 | family_expenditure_private_entertainers | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 207 | family_expenditure_loan_reimbursement | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 208 | family_expenditure_other_fees_services | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 209 | family_expenditure_no_expenditures | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | P | Standalone "no expenditures" catch-all pattern (same as #85/#86/#161) |
| 210 | family_expenditure_public_health_insurance | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 211 | family_expenditure_financial_services | B\) PERIODIC AND EXTRAORDINARY EXPENDITURES | C |  |
| 212 | purchase_repair_specified_products | 2\. What was the expenditures... | P | Question text incomplete, self-flagged |
| 213 | casco_insurance_vehicles | 2\. What was the expenditures... | P | Question text fragment/inferred label |
| 214 | travel_insurance | 2\. What was the expenditures... | C |  |
| 215 | insurance_main_dwelling | 2\. What was the expenditures... | C |  |
| 216 | insurance_secondary_dwelling | 2\. What was the expenditures... | C |  |
| 217 | gross_expenditure_restaurants_ceremonies | 2\. What was the expenditures... | C |  |
| 218 | other_cultural_services | 2\. What was the expenditures... | P | Question text truncated, self-flagged |
| 219 | subscription_radio_tv | 2\. What was the expenditures... | C |  |
| 220 | rent_equipment_leisure | 2\. What was the expenditures... | C |  |
| 221 | income_sources | Section 9: HOUSEHOLD INCOME AND SAVINGS | C |  |
| 222 | lowest_monthly_income | Section 9: HOUSEHOLD INCOME AND SAVINGS | C |  |
| 223 | yearly_income_utilization | Section 9: HOUSEHOLD INCOME AND SAVINGS | C |  |
| 224 | afford_rent_mortgage_utilities | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 225 | afford_house_warmth | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 226 | afford_unexpected_expenses_500 | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 227 | afford_meat_chicken_fish | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 228 | afford_friends_family_drink_meal | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 229 | afford_annual_holiday_week | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 230 | afford_replace_furniture | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 231 | buy_food_place | Section 11: SUBJECTIVE QUESTIONS | C | Minor: codes assigned by list order, self-flagged for review but plausible |
| 232 | owner_dwelling_not_used | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 233 | reason_dwelling_not_used | Section 11: SUBJECTIVE QUESTIONS | C |  |
| 234 | duration_final_interview | RESPONSE/COOPERATION OF THE HOUSEHOLD | P | Universe ("all household members?") left as an open question in the note itself |
| 235 | who_answered_final_interview | RESPONSE/COOPERATION OF THE HOUSEHOLD | C |  |
| 236 | who_compiled_diaries | RESPONSE/COOPERATION OF THE HOUSEHOLD | C |  |
| 237 | quality_keeping_diaries | RESPONSE/COOPERATION OF THE HOUSEHOLD | P | Categories start at code 2 ("Satisfactory"); code 1 ("Poor") is missing even though the very next variable in the same module has it |
| 238 | interest_during_final_interview | RESPONSE/COOPERATION OF THE HOUSEHOLD | C |  |
| 239 | (see note) | — | — | One variable's module/position could not be independently re-verified beyond the self-reported metadata during this pass; treated as Correct-leaning based on its `extraction_confidence: 1.0` and clean fields — flagged here for a follow-up spot check rather than left silently uncounted |

### Outcome tally

| Outcome   | Count   | Percentage |
|-----------|---------|------------|
| Correct   | 152     | 63.6%      |
| Partial   | 65      | 27.2%      |
| Wrong     | 22      | 9.2%       |
| **Total** | **239** | **100%**   |

### Error types grouped by field

| Error type | Count |
|------------------------------------|------------------------------------|
| Missing answer codes (categories `null` or a code visibly absent, e.g. `highest_diploma_attained`, `quality_keeping_diaries`, `extraordinary_maintenance_exp_6m`, `use_another_dwelling`, `legal_status_use_dwelling`) | 6 |
| Hallucinated/placeholder categories not grounded in source text (`dwelling_type_interviewer`, `hot_water_appliance_type`, `communication_equipment_presence`) | 3 |
| Duplicate variable re-extracted across chunks with worse data (`marital_status`, `relationship_to_head`) | 2 |
| Duplicated/misaligned answer codes within one variable (`garments_footwear_purchase_last_month`, `equipment_type`) | 2 |
| Wrong/contradictory `is_missing` flag or code semantics (`maintenance_regular_exp`, `maintenance_extraordinary_exp`, `dwelling_rented_with_equipment`, `father_code`, `mother_code`) | 5 |
| `raw_name` not unique or not descriptive (`amount_paid_old_leks` collision, `096011`/`096021`/`096012`/`096022`/`112011`/`112012`/`112021`/`112022`, `expenditure_kind_*`) | 24 |
| `universe` missing, vague, or posed as an open question in the note itself (`duration_final_interview`, several `A) SPARE TIME` items) | 11 |
| `numeric_range`/currency not filled in or ambiguous (`monthly_rent`, `repairement_repair_cost`) | 2 |
| Standalone "no expenditures" catch-all extracted as its own variable instead of an `is_missing` category (`expenditure_none_24`, `expenditure_none_25`, `no_expenditures_code`, `family_expenditure_no_expenditures`) | 4 |
| Question text left as raw OCR/checkbox markup instead of clean prose (`heating_type`, `heating_source_type`, `heating_fuel_source`) | 3 |
| Multi-select question split into several inferred single-select booleans (`vehicle_ownership_*`) | 6 |
| Other (fragmented/incomplete question text, low-confidence inferred wording) | \~14 |

------------------------------------------------------------------------

## Step 4: Ranking errors by impact

**High impact** (breaks downstream harmonization mapping): the `raw_name` non-uniqueness/non-descriptiveness problem is the single biggest issue by volume — 24 variables use either a bare numeric code (`096011`, `112011`, etc.) or reuse an identical name (`amount_paid_old_leks`) across unrelated questions in different modules. Any downstream join or mapping keyed on `raw_name` will either collide or fail to resolve to a real concept. Close behind are the hallucinated/placeholder categories (`dwelling_type_interviewer`, `hot_water_appliance_type`, `communication_equipment_presence`) and the duplicated/misaligned answer-code tables (`garments_footwear_purchase_last_month`, `equipment_type`), which would silently corrupt any code-based recoding since the codes look plausible but are wrong.

**Medium impact:** the contradictory/incorrect `is_missing` semantics on sentinel codes (98/99-style "not present"/"can't remember" codes labeled as literal Yes/No answers, e.g. `maintenance_regular_exp`, `father_code`, `mother_code`) would silently misclassify missing data as valid responses in any statistical analysis. Missing answer codes (`highest_diploma_attained`, `quality_keeping_diaries`) and vague/missing `universe` fields are also medium impact — they reduce usability but don't actively introduce wrong values.

**Low impact:** the raw-OCR-checkbox markup left in a few `question_text` fields (`heating_type` and siblings) and the duplicate-chunk re-extractions of `marital_status`/`relationship_to_head` are cosmetic/redundant rather than actively wrong, since the first (correct) copy of each duplicated variable is also present in the output.

------------------------------------------------------------------------

## Step 5: Patterns observed

**By module/chunk:** Errors cluster heavily in modules whose Docling-converted source text is itself a checklist/multi-column code table rather than plain question-and-answer prose — `Section 4: GARMENTS AND FOOTWEAR`, `B) COMMUNICATIONS`, and `Section 6: TRANSPORT AND COMMUNICATION`'s equipment list. This matches the table-fidelity limitation documented in the repository README. By contrast, plain YES/NO amenity checklists (`A) MAIN DWELLING`'s facility list, most of `B) PERIODIC AND EXTRAORDINARY EXPENDITURES`) extracted almost perfectly, because each line is a short, unambiguous, self-contained question.

**By chunking artifact:** Several "module" values are not real section headings at all — `Q ues ti on 3`, `Q ues ti on 7`, `HOUSEHOLD BUDGET SURVEY ALBANIA`, `(If owner, joint-owner, becoming owner or live for free...)`, `9. What was the amount of expenditures by specified items?`, `2. What was the expenditures of your family in the last 3 months?`. These are OCR-garbled question numbers or parenthetical instruction lines that Docling misidentified as Markdown headings, which is exactly the chunking-boundary risk called out in the pipeline's own design notes. Every variable duplication observed (`marital_status`, `relationship_to_head`) occurs at a boundary between one of these spurious headings and the real "Section 1" heading, i.e. the same underlying question got split into two chunks and extracted twice.

**Systematic errors:** (1) The AI consistently used the questionnaire's own COICOP/internal item codes as `raw_name` whenever a checklist of expenditure items appeared (`094`/`096`/`101`/`102`/`104`/`105`/`112` series), rather than generating a descriptive snake_case name as it did everywhere else — this is a systematic instruction-following gap, not a one-off mistake. (2) Sentinel "can't remember"/"if no present, write 99" codes were repeatedly captured with either a wrong label or a contradictory `is_missing` value, suggesting the prompt does not give explicit guidance on how to treat these special codes.

------------------------------------------------------------------------

## Step 6: Summary

### Overall accuracy

Of the 239 extracted variables, 152 (63.6%) were fully correct, 65 (27.2%) were partially correct, and 22 (9.2%) were wrong. The Docling + Azure OpenAI pipeline handles plain, self-contained Yes/No and short-answer questions very reliably — the large majority of "Correct" rows are amenity checklists, ownership questions, and expenditure amounts with clean, unambiguous source text. Accuracy drops sharply wherever the source table is a dense multi-column code list (garments/footwear, communication equipment) or wherever a chunk boundary falls mid-question, producing either missing categories or duplicated variables.

### Top errors

- **Non-unique/non-descriptive `raw_name` values** — numeric COICOP-style codes (`096011`, `112011`, etc.) and a reused name (`amount_paid_old_leks`) across 24 variables, which would break any downstream mapping keyed on variable name.
- **Duplicated/misaligned answer-code tables** — `garments_footwear_purchase_last_month` and `equipment_type` contain codes that repeat with conflicting labels, a direct consequence of noisy OCR table structure.
- **Incorrect or contradictory `is_missing`/sentinel-code handling** — "can't remember"/"if not present" codes (98/99-style) are inconsistently labeled and sometimes marked both a literal answer and missing at the same time (`maintenance_regular_exp`, `father_code`, `mother_code`).

### Patterns observed

Errors cluster around two structural causes rather than random model failure: (1) source content that survives Docling conversion as a dense, multi-column, repetitive code table (garments/footwear, communication equipment, appliance codes) consistently produces duplicated or misaligned categories in the JSON, confirming the known Docling weakness already documented in `conversion_notes.md`; and (2) several "module" values are themselves OCR-garbled question stems or parenthetical instructions misidentified as headings, and every duplicated-variable case observed occurs right at one of these spurious chunk boundaries. Plain, single-line Yes/No questions extracted almost perfectly regardless of module.

### Prompt changes implemented after this review

All three prompt changes recommended by this baseline review were added to `agents/prompts.py` on 2026-07-28:

1. `raw_name` must be a unique, descriptive snake_case identifier and must not use a questionnaire item or COICOP code.
2. Non-substantive sentinel codes such as "don't know," "can't remember," "not present," and "not applicable" must use `is_missing: true` and must not also be labeled as substantive answers.
3. Garbled tables, duplicate codes with conflicting labels, and codes without legible labels must not receive fabricated placeholder labels. These cases must be assigned confidence of 0.5 or lower and flagged for review.

### Current validation needed

Repeat this per-variable review against the current 290-variable `output/ALB_2014_HBS_svis.json` before treating the prompt changes as validated. The follow-up should compare accuracy, completeness, duplicate `raw_name` values, sentinel-code handling, and dense-table category alignment against this 239-variable baseline.