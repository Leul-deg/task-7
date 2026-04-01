# Business Logic Questions

## 1. Credit Score Point Values
- **Question:** Prompt says "e.g., on-time +2, late cancel −1, no-show −3, upheld dispute −5" — is this exact or example guidance?
- **Understanding:** The "e.g." prefix signals these are illustrative. The actual values should be tuned for the studio's risk tolerance.
- **Solution:** Implemented with adjusted values (+5 / −10 / −20 / +10) that create sharper differentiation between good and bad behavior. Base score 100, range 0–200.

## 2. Credit Threshold for Booking Restriction
- **Question:** Prompt says "below a threshold score" requires staff approval but doesn't specify the threshold.
- **Understanding:** The threshold should be low enough that only repeat offenders are affected.
- **Solution:** Two tiers — score < 40 requires staff approval ("pending_approval" status); score < 20 blocks booking entirely.

## 3. Cancellation vs. Reschedule Breach
- **Question:** Should rescheduling within the 12-hour window count as a breach identical to cancellation?
- **Understanding:** Rescheduling is a less harmful action since the customer still intends to attend. However, the old session's spot is still affected.
- **Solution:** Rescheduling within 12 hours records a breach on the old reservation (same as cancel) because the freed spot may not be filled in time.

## 4. Who Can Leave Reviews — Both Sides?
- **Question:** Prompt says "both customer and staff can leave a star rating." Does "staff" mean the instructor only, or any staff member?
- **Understanding:** Only the instructor who ran the session has first-hand experience to review a customer's participation.
- **Solution:** Review eligibility is limited to the booking customer and the assigned instructor for that session.

## 5. Appeal Credit Impact Direction
- **Question:** Prompt says "upheld dispute −5" — does the penalty apply to the review author or the person who filed the appeal?
- **Understanding:** An upheld dispute means the review was found to be problematic, so the review *author* should be penalized, not the appealer.
- **Solution:** Upheld appeal deducts credit from the review author and removes the review. Rejected appeal has no credit impact on either party.

## 6. Waitlist Promotion — Automatic or Manual?
- **Question:** Should waitlisted users be auto-promoted when a spot opens, or should they be notified and given a window to confirm?
- **Understanding:** Given the offline-first design and fast booking cycles, manual confirmation would add friction and risk the spot going unfilled.
- **Solution:** Fully automatic — cancellation immediately promotes waitlist #1 to a confirmed reservation.

## 7. Content Versioning — What Triggers a New Version?
- **Question:** Prompt says "publish versioned updates" but doesn't define what constitutes a version boundary.
- **Understanding:** Every save should snapshot the previous state so editors can rollback to any prior point.
- **Solution:** Every save (create or update) creates a ContentVersion snapshot of the state *before* the edit. Rollback restores from any version and resets status to "draft" for re-review.

## 8. Dwell Time — Tab Visibility
- **Question:** Should heartbeat fire when the browser tab is in the background?
- **Understanding:** Background tabs don't represent active reading. Counting them would inflate dwell time metrics.
- **Solution:** Heartbeat JS checks `document.visibilityState === 'visible'` before firing. Only active-tab time is counted.
