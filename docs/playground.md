# Static Sample Explorer

This explorer contains **precomputed synthetic data**. It does not run Survey
Scribe or contact a model. Use the three result states to learn how output,
diagnostics, and failed blocks affect status.

<div class="static-playground" data-static-playground>
  <p class="playground-boundary"><strong>Static safety boundary:</strong> no upload, questionnaire entry, credential entry, browser storage, cookies, backend, or live inference.</p>
  <div class="playground-tabs" role="tablist" aria-label="Precomputed result samples">
    <button id="sample-tab-success" type="button" role="tab" aria-selected="true" aria-controls="sample-panel" tabindex="0" data-sample="success">Success</button>
    <button id="sample-tab-partial" type="button" role="tab" aria-selected="false" aria-controls="sample-panel" tabindex="-1" data-sample="partial">Partial</button>
    <button id="sample-tab-failed" type="button" role="tab" aria-selected="false" aria-controls="sample-panel" tabindex="-1" data-sample="failed">Failed</button>
  </div>
  <section id="sample-panel" class="playground-panel" role="tabpanel" aria-labelledby="sample-tab-success" tabindex="0">
    <div class="playground-summary">
      <p><span class="status-chip" data-status></span></p>
      <dl>
        <div><dt>Usable variables</dt><dd data-variable-count></dd></div>
        <div><dt>Diagnostics</dt><dd data-diagnostic-count></dd></div>
        <div><dt>Failed blocks</dt><dd data-failed-count></dd></div>
        <div><dt>Default CLI exit</dt><dd data-default-exit></dd></div>
        <div><dt>Strict CLI exit</dt><dd data-strict-exit></dd></div>
      </dl>
    </div>
    <div class="playground-columns">
      <section aria-labelledby="sample-variables-heading">
        <h2 id="sample-variables-heading">Variables</h2>
        <div class="table-scroll" tabindex="0" role="region" aria-label="Synthetic variable table">
          <table>
            <thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Review</th></tr></thead>
            <tbody data-variables></tbody>
          </table>
        </div>
      </section>
      <section aria-labelledby="sample-diagnostics-heading">
        <h2 id="sample-diagnostics-heading">Diagnostics</h2>
        <ul data-diagnostics></ul>
      </section>
    </div>
    <details>
      <summary>Inspect precomputed result JSON</summary>
      <pre tabindex="0"><code data-result-json></code></pre>
    </details>
  </section>
</div>

<script id="playground-data" type="application/json">
{
  "success": {
    "status": "success",
    "default_exit": 0,
    "strict_exit": 0,
    "result": {
      "survey_id": "SYN_2026_HHS",
      "variables": [
        {"raw_name": "age", "data_type": "numeric", "needs_review": false},
        {"raw_name": "employment", "data_type": "categorical_single", "needs_review": true}
      ],
      "diagnostics": [
        {"code": "QUALITY_MISSING_CATEGORIES", "severity": "warning"}
      ],
      "failed_blocks": []
    }
  },
  "partial": {
    "status": "partial",
    "default_exit": 0,
    "strict_exit": 1,
    "result": {
      "survey_id": "SYN_2026_HHS",
      "variables": [
        {"raw_name": "age", "data_type": "numeric", "needs_review": false}
      ],
      "diagnostics": [
        {"code": "SOURCE_UNREADABLE", "severity": "error"}
      ],
      "failed_blocks": [
        {"block_id": "source-page-2", "message": "One synthetic page was unreadable."}
      ]
    }
  },
  "failed": {
    "status": "failed",
    "default_exit": 1,
    "strict_exit": 1,
    "result": {
      "survey_id": null,
      "variables": [],
      "diagnostics": [
        {"code": "PROVIDER_FAILED", "severity": "error"}
      ],
      "failed_blocks": [
        {"block_id": "chunk-000001", "message": "The synthetic chunk did not produce usable output."}
      ]
    }
  }
}
</script>

## How to read the states

- **Success** has usable output and no operational failure. Review warnings can
  still be present.
- **Partial** has usable output plus an operational failure. The default CLI exit
  is zero after required artifacts are written; `--strict` makes it nonzero.
- **Failed** has no usable output. Both default and strict CLI modes exit nonzero,
  and no result artifact is written.

The records are explanatory examples, not accuracy evidence. They were written
for this site and do not come from a real respondent, questionnaire, or provider.
