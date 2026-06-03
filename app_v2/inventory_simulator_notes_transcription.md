# Enterprise Inventory Simulator — Handwritten Review Notes

*Transcription of Adobe_Scan_03_Jun_2026.pdf (14 pages). Ambiguous words flagged with `[?]`.*

---

## Page 1

Although I never really defined anything I see revenue, Logs and margin section pre entered.

**Next up → The exception cockpit**

This should be more clear as to what exactly changed, it simply says inputs changed since last solve. → What inputs? What else could we notify?

The font that says ex: procurement plan is stale is also not good)

Solver input readiness is another tab that just feels like pre done and doesn't update. Check and confirm

Also The order of listed direction of every solver unusually shows 7.

I Ideally am starting to lean on that — do we need a onboarding questions that we need To ask a user so we would present what he needs? [So we have setup in next page, just noticed — could that be made better]

A user working (or) manufacturing a single sku doesn't need profit mix to exist ideally and what else?

I think above exception cockpit we need to ask a set of questions to identify what a user needs and hand hold them. Ex: Do you think a user understands after

---

## Page 2

looking at the UI as to what profit mix means? → How would it be? Ex: Profitmix — Identify the best sku to produce considering so and so stuff. Maybe if it has to be detailed when I click them on it can explain these stuff clearly.

And going back to the Exception cockpit it could have one nice resolve all button at top (or) after proper explain just resolve at each stage.

Now, back at Plan freshness, can't we unify input readiness and freshness to be more useful instead of wasting as two useless state? Cause stale messages also go in exception, so if we want a better approach sure it's fine To have than here too but how do you make this better — what does "As of" record?

I also think exception ledger and value ledger should be unified and every subsequent action timeStamped and its impact of that decision explained clearly too.

Okay, I may be misunderstanding what the value ledger surfaces on — I right with the interpretation?

---

## Page 3

### 01 — I am now looking at setup Tab:

I see that base currency INR 84.2/$ [?] is hardcoded. What does effective tax denote? Service level — doesn't it change often or per period? Or is it correct to define that there? CIN is also uneditable. Is this all the useful details?

MSME also comes prefilled with entries but I think the key issue is that like a company may continue of adding plant & machinery — so is it combined value of all, yeah? And these 2 questions are enough? & What's the output saying NOT MSME? What are they then?

Where do you Track receivables for a company? A company may sell its product directly to customers, In which case this may be useless info, am I right?

I also doubt the effectiveness & accuracy of Industry Templates.

Is That all the questions for the planning profile? Where is pure MTS? what's ATO?

What do you understand from capacity tightness. And The what this switches off section also doesn't [conversion x...]

---

## Page 4

work properly. As to what it tries to tell & changes done in profile doesn't update here clearly.

Planning calendar is another poorly done segment. Can't you fit in a actual calendar so I could choose directly at start date — do you Think a user understands this section clearly? Horizon → Do you think he understands this? And I selected horizon as 52 days. But at bottom it says W23 / Jun 26 To W21 24 May 27 — rupee symbol and service level should be ideally here I think.

Why on earth does a user has To again compute Calendar and get the output which is also unclear. There is already a website that shows all gazetted holidays and if it has to be computed it is just idle & separate while it should be integrated & outputs matched.

What happens when a user chooses any other state? No option for him to update whether a day in the period is holiday or not? Or how to structure such cases.

---

## Page 5

### 02 — PRODUCTS TAB:

Finished goods catalogue → currently fully read only and uneditable, fully unnecessary segment. Are all the inputs in the finished goods catalogue, every single one of them, are they actually useful (or)? What is TAT %? What I am Trying to understand is — There are many units of measurements that get defined for a finished good and for each finished goods raw material. Put yourself in the shoe of a user trying to define his whole product. At Top you let the user select a product, then you have them enter every single finished good, then you ask yield & expiry → This is for what product? How would the user be sure of —

OKay I see there is a explanation as to product Name, But can't you like build a unified version where it could be interpreted easy.

Now costs section also is uneditable prefilled stuff which also doesn't define what products I am looking at. I am also not sure if the elements asked are all that is needed and are actually getting fed → what is setup (amort.), conversion & CH? [?]

---

## Page 6

Also questions like setup amortized over lot of 120u? when did I define a lot? & If I have multiple products how does the interpretation be done?

And as you said going from one product A to product B may have One setup cost and going from B to A may have another. How do we get to define such stuff? Or is it not needed here? & ?

Is that all the details that is needed in Bill of Materials? Are you sure, can you verify?

And below it there is more stupid stuff That is Totally like — how exactly should a changeover in price get recorded really? I choose a planning horizon & go ahead with a fixed price for each part & by the next time, I am to like view the PO release schedules — it could be that The price of the product part may have updated & where exactly should this be presented?

Where does a user record such changes?

— A change in price as of date, gets recorded in activity, PO price shows increased costs etc...

---

## Page 7

There are still so many structural definitions I think but I am too down at the moment to get complete picture.

Like even if I get MTS forecasted, then I need To know based on S&OP analysis then decide how much To procure and produce, what policy to be applied ideally comes when?

And a user may come in with a known demand schedule for The period & may just have To upload That, scheduled receipts, the on hand amounts, the etc -. The visualisation part is needed & fed for MILP To Tell what (or) how much to procure yeah?

### 03 — Now Network Tab

Another useless prefilled table — when did I ever define the structure! Everything is wrong with that visualisation? Why would it be That flow is not like WH-CHN to DC BLR & from here to DC pune while it could be from WH-CHNS to DC pune directly. So many such stupid useless stuff.

What exactly do you understand from this again? Do you know the cost & Transport trunk only to be carried? More info — crucial stuff is missing.

---

## Page 8

Then more stupidity — when exactly should a inventory policy be defined again? It auto derives policies, shows EOQ at one section and a quantity then also shows (R, Q) periodic & so on at other. 1st — did you even define (or) does this have a understanding of what if it's a one off order?

A user may constantly add more order requirements / quantities. Do you 1st have any clue as to what is the demand for any of these products are? MTS → how much is the requirement Demand? MTO → how much is the " " " "?

You have no information for any such stuff & how exactly did you come up with this?

Now you present a section called Make to order. This is just stupid. And everything uneditable & fixed. You put orders by requirement due date and you also produce (or) To say sort Them by then profit mix levels? etc..

Had I chosen MTS then I would require that for The period I need to demand forecast for That product so I know how much to produce, what is the expected MAPE, based on These then other stuff.

---

## Page 9

On hand & you are going to define scheduled receipts that are about To be received from Supplier Separately?

### 04 — Demand planning:

Whenever I open this tab it automatically says Running, without any info having input by me. And returns a po Api / forecast failed message.

I asked previously — is this The format to input data? Do you recognise & based on product information defined In previous Tabs, you could show a sample of exactly how to define a part and a row properly?

Import history format is also dumb, no clue what product it is even for.

At bottom I think you could have a combined results tab that shows unified data for all products — some may have been MTO Type & already have a predefined set of orders and other cases.

What the hell happened to history & forecast charts? It used to show a nice graph, now what on earth is this like heart spikes?

---

## Page 10

I am shocked — like what exactly do you even feed into any of these solvers.

The every section here is a prefilled mistake with crucial info missing to be asked structurally — every section has random stuff.

Why on earth is there a time varying price graph here? And it is also prefilled. Maybe this will be helpful to record in activity tab to note down any price changes with dates of such changes recorded nicely as said graphs.

No clue what product I am entering any of these details for. In previous tab you already asked to define each subpart for a product, now there is good supplier master but everything feels far off from definitions. If this has to be done do this properly. Why is everything annualized? Spend & OTIF are just trash & prefilled with no right way to do this.

Opening on hand also just kind off random & not sure if it actually is used anywhere with this uneditable segment. You define

---

## Page 11

I don't really understand the NPI like module. I move it for now — not delete, just remove from UI & record elsewhere what it does.

So many sections I genuinely am curious If they add value & if they do how it would look like & If they could be made any better.

Segmentation & lifecycle goes here — inventory policy tab in products already got shit rolling, like what the fuck. And how exactly did you categorise that shit?

There's committed demand tab — is it correct placement? S&OP determines how much exactly to be made no?

### 05 — S&OP.

No clue for what product I am looking at.

I think for all tabs inputs could have for separate sections but solver has to output a unified version, but right now no way for user to confirm what products he defined fully correct.

---

## Page 12

Every single subsection is prefilled Trash → How did you know?

Is every section even correct? You have defined labor wgs [wages?] in here but you define lines for each product in next Tab.

Workers — I thought should get defined in production Tab & also prefilled.

Disaggregation → Also prefilled, no clue what It does. Same for gmp [?] to target.

₹.

### 06 — Production architecture:

Every single section is uneditable & prefilled.

No proper way to define a line & how many workers and machines It may have, cycle time for each stage & product as a whole.

Cycle time requirement is in page 2 while It already shows a prefilled graph in page 1.

I said I may use OEE term (or) just go with cycle time to simplify?

---

## Page 13

Shutdown threshold, campaign min - run — what the fuck are even these?

Change matrix, choose rm order — all uneditable & prefilled.

### 07 — Suppliers & procurement:

This should have been integrated with products Tab I think, a lot of my complaints follow across these tabs, still lot more section here are separate, confusing, unclear what Am I even looking at.

Remove the external signal section for now, It isn't done properly at all. What do I even interpret from that?

Put incoterm responsibility matrix in team section.

Improvise other section like sourcing lacing [?] and other inputs.

So many other prefilled uneditable segments...

---

## Page 14

The next tab after sourcing — when I click it entire page freezes and I am none able to open The deployed app again. I ~~have to state~~ [struck out]

Console tab also shows up as empty.
