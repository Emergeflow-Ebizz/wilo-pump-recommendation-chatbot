(function () {
  "use strict";

  // Prevent scroll on mobile - lock viewport
  if (window.innerWidth <= 1024) {
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    document.body.style.position = 'fixed';
    document.body.style.width = '100%';
    document.body.style.height = '100%';

    // Prevent scroll with touch
    document.addEventListener('touchmove', function(e) {
      if (e.target.closest('.thread')) return; // Allow scrolling in thread
      e.preventDefault();
    }, { passive: false });

    // Prevent scroll with wheel
    document.addEventListener('wheel', function(e) {
      if (e.target.closest('.thread')) return; // Allow scrolling in thread
      e.preventDefault();
    }, { passive: false });

    // Prevent pinch zoom
    document.addEventListener('touchstart', function(e) {
      if (e.touches.length > 1) {
        e.preventDefault();
      }
    }, { passive: false });

    // Prevent double-tap zoom
    var lastTouchEnd = 0;
    document.addEventListener('touchend', function(e) {
      var now = Date.now();
      if (now - lastTouchEnd <= 300) {
        e.preventDefault();
      }
      lastTouchEnd = now;
    }, { passive: false });
  }

  // ---------------------------------------------------------------------
  // Backend config
  // ---------------------------------------------------------------------
  // Requires CORS enabled on the FastAPI side. Since this page is opened via
  // file://, the browser sends Origin: null, so the backend's
  // CORSMiddleware needs allow_origins=["*"] (a specific origin won't match).
  //
  // The FastAPI app is mounted at /api via index.py, so all requests need /api prefix.
  // When running locally with uvicorn api.index:app, routes are at /api/...
  // On Vercel, vercel.json routes "/api/(.*)" to api/index.py which also uses /api
  // Dynamically determine API URL based on environment
  var API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000'
    : '/api';

  function prettifyKey(key) {
    return key
      .replace(/_/g, " ")
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function formatDetailValue(value) {
    if (typeof value === "number" && !Number.isInteger(value)) {
      return String(Math.round(value * 100) / 100);
    }
    return String(value);
  }

  // next_question's "unit" field (e.g. borewell_size -> "inch") is display-only,
  // it's never asked as its own question, but /recommend still requires a
  // companion "<field>_unit" answer. The naming doesn't follow one consistent
  // rule (borewell_size -> borewell_unit, well_depth -> well_depth_unit), so
  // known cases are mapped explicitly; anything new falls back to "<key>_unit"
  // and is harmless to send even when unused, since the backend ignores
  // extra fields it doesn't recognize.
  var UNIT_FIELD_OVERRIDES = {
    borewell_size: "borewell_unit",
    well_depth: "well_depth_unit",
    total_area: "area_unit",
  };
  function unitFieldNameFor(key) {
    return UNIT_FIELD_OVERRIDES[key] || key + "_unit";
  }

  // Fixed-choice questions that go through /answer_category (ParsedCategory)
  // instead of /answer (ParsedAnswer).
  var CATEGORY_QUESTION_KEYS = ["delivery_type", "inside_or_outside", "horizontal_or_vertical", "heating_system"];

  function getPumpImagePath(modelName) {
    if (!modelName) return null;
    var imageFolderPath = "./Wilo Pump Images/";
    var modelUpper = modelName.toUpperCase();
    var pumpImages = {
      "YONOS PICO": imageFolderPath + "Yonos%20PICO.png",
      "YONOS MAXO": imageFolderPath + "Yonos%20MAXO.png",
      "STRATOS PICO": imageFolderPath + "Stratos%20PICO.png",
      "STRATOS MAXO": imageFolderPath + "Stratos%20MAXO.png",
      "PARA MAXO": imageFolderPath + "Para%20MAXO.png",
      "PARA": imageFolderPath + "Para.png",
      "STAR-Z": imageFolderPath + "Star%20Z_Common%20for%20all%20models.png",
      "WBWP3": imageFolderPath + "WBWP3-WBWP4.jpg",
      "WBWP4": imageFolderPath + "WBWP3-WBWP4.jpg",
      "WBW3": imageFolderPath + "Wilo-WBW6-WBW7-WBW8.jpg",
      "WBW6": imageFolderPath + "Wilo-WBW6-WBW7-WBW8.jpg",
      "WBW7": imageFolderPath + "Wilo-WBW6-WBW7-WBW8.jpg",
      "WBW8": imageFolderPath + "Wilo-WBW6-WBW7-WBW8.jpg",
      "WPOV": imageFolderPath + "WPOV.png",
      "WPO": imageFolderPath + "WPO%20Raptor.jpg",
      "FMHIL": imageFolderPath + "FMHIL.png",
      "HMHIL": imageFolderPath + "HMHIL.jpg",
      "CO 2MHIL": imageFolderPath + "CO%202%20MHIL.png",
      "CO 2MHI": imageFolderPath + "CO%202%20MHIL.png",
      "MHIL": imageFolderPath + "MHIL.jpg",
      "VMHIL": imageFolderPath + "VMHIL.png",
      "CIFAC": imageFolderPath + "CIFAC.jpg",
      "FAC": imageFolderPath + "FAS%2CFAC.jpg",
      "FAS": imageFolderPath + "FAS%2CFAC.jpg",
      "HWJ": imageFolderPath + "HWJ.png",
      "MNC": imageFolderPath + "MNC.jpg",
      "MPM": imageFolderPath + "MPM.jpg",
      "PB": imageFolderPath + "PB.jpg",
      "PUN": imageFolderPath + "PUN.jpg",
      "PW": imageFolderPath + "PW%20Boost%2005.jpg",
      "RLTC": imageFolderPath + "RLTC.png",
      "WHS": imageFolderPath + "WHS.png",
      "CHALLENGER": imageFolderPath + "Challenger.jpg",
      "REXA": imageFolderPath + "Rexa%20PRO-S.jpg",
      "STAR": imageFolderPath + "Star%20RS.jpg",
      "INITIAL WASTE": imageFolderPath + "Initial%20Waste.jpg",
      "MINI": imageFolderPath + "Mini.jpg",
      "HI PERI": imageFolderPath + "Hi%20Peri.png",
      "KUSHAL": imageFolderPath + "WMB%20Kushal.png",
    };
    var keys = Object.keys(pumpImages).sort(function(a, b) {
      return b.length - a.length;
    });
    for (var i = 0; i < keys.length; i++) {
      if (modelUpper.indexOf(keys[i]) !== -1) {
        return pumpImages[keys[i]];
      }
    }
    return null;
  }


  // ---------------------------------------------------------------------
  // Conversation flow. The application question and lead-capture are fixed;
  // everything about sizing the pump (which questions to ask, in what order)
  // is driven live by the backend's /{slug}/next_question endpoint.
  // ---------------------------------------------------------------------
  var contactValidate = function (value) {
    var trimmed = value.trim();
    if (/^\d{10}$/.test(trimmed) || /^\S+@\S+\.\S+$/.test(trimmed)) return null;
    return "Please enter a valid email address or 10-digit phone number.";
  };
  var pincodeValidate = function (value) {
    var trimmed = value.trim().replace(/\s/g, "");
    if (/^\d{4,10}$/.test(trimmed)) return null;
    return "Please enter a valid pin code (6 digits) or zip code (4-10 digits).";
  };
  var nameValidate = function (value) {
    var trimmed = value.trim();
    return trimmed.length >= 2 ? null : "Please enter a valid name (at least 2 characters).";
  };
  var emailValidate = function (value) {
    var trimmed = value.trim();
    return /^\S+@\S+\.\S+$/.test(trimmed) ? null : "Please enter a valid email address.";
  };

  var FLOW = [
    {
      id: "language",
      kind: "options",
      bot: function () {
        return "Please select your preferred language.";
      },
      options: [
        {
          label: "English",
          value: "english",
        },
        {
          label: "Chinese",
          value: "chinese",
        },
        {
          label: "Korean",
          value: "korean",
        },
        {
          label: "Turkish",
          value: "turkish",
        },
      ],
      next: function () {
        return "country";
      },
    },
    {
      id: "country",
      kind: "options",
      bot: function () {
        return "Please select your country.";
      },
      options: function () {
        var selectedLanguage = state.answers.language;
        var countryOptions = [
          {
            label: "India",
            value: "india",
          },
          {
            label: "China",
            value: "china",
          },
          {
            label: "Korea",
            value: "korea",
          },
          {
            label: "Turkey",
            value: "turkey",
          },
        ];

        // If language is selected, prioritize matching country
        if (selectedLanguage === "chinese") {
          return countryOptions.filter(function(c) { return c.value === "china"; })
            .concat(countryOptions.filter(function(c) { return c.value !== "china"; }));
        } else if (selectedLanguage === "korean") {
          return countryOptions.filter(function(c) { return c.value === "korea"; })
            .concat(countryOptions.filter(function(c) { return c.value !== "korea"; }));
        } else if (selectedLanguage === "turkish") {
          return countryOptions.filter(function(c) { return c.value === "turkey"; })
            .concat(countryOptions.filter(function(c) { return c.value !== "turkey"; }));
        }

        return countryOptions;
      },
      next: function () {
        return "application";
      },
    },
    {
      id: "application",
      kind: "options",
      bot: function () {
        return "Please select an application.";
      },
      options: [
        {
          index: 1,
          label: "Pressure Boosting",
          value: "pressure-boosting",
          icon: "./Pressure Boosting.png",
          description: "Boost water pressure for residential and commercial supply systems",
        },
        {
          index: 2,
          label: "Heating Circuit",
          value: "heating-circuits",
          icon: "./Heating Circuits.png",
          description: "Circulate hot water in heating systems and radiators",
        },
        {
          index: 3,
          label: "Domestic Hot Water",
          value: "domestic-hot-water",
          icon: "./Domestic Hot Water.png",
          description: "Supply hot water for domestic use in homes and buildings",
        },
        {
          index: 4,
          label: "Dewatering",
          value: "dewatering",
          icon: "./Dewatering.png",
          description: "Remove water from construction and mining sites",
        },
        {
          index: 5,
          label: "Borewell to Overhead Tank",
          value: "water-transfer",
          icon: "./Borewell to Overhead tank.png",
          description: "Transfer water from boreholes to overhead storage tanks",
        },
        {
          index: 6,
          label: "Bottom Tank to Overhead Tank",
          value: "tank-filling",
          icon: "./From Bottom tank to Overhead tank.png",
          description: "Fill overhead tanks from ground level storage",
        },
      ],
      next: function (value) {
        if (value === "water-transfer") return "__dynamic__water_transfer";
        if (value === "tank-filling") return "__dynamic__tank_filling";
        if (value === "pressure-boosting") return "__dynamic__pressure_boosting";
        if (value === "dewatering") return "__dynamic__dewatering";
        if (value === "heating-circuits") return "__dynamic__heat_circulation";
        if (value === "domestic-hot-water") return "__dynamic__domestic_hot_water";
        return "coming-soon";
      },
    },
    {
      id: "coming-soon",
      kind: "options",
      bot: function () {
        return "That application isn't available yet, we're still adding support for it. For now you can try Water Transfer, or pick another application below.";
      },
      options: [
      ],
      next: function () {
        return "application";
      },
    },
    {
      id: "lead-email",
      kind: "input",
      bot: function () {
        return "";
      },
      placeholder: "Email address",
      validate: function (value) {
        var trimmed = value.trim();
        if (state.isRejectionFlow) {
          return null;
        }
        return emailValidate(value);
      },
      optional: function () {
        return state.isRejectionFlow;
      },
      next: function () {
        if (state.isRejectionFlow) {
          // In rejection flow, check if email was actually provided
          var email = state.answers["lead-email"];
          console.log("[lead-email next] isRejectionFlow:", state.isRejectionFlow, "email provided:", email);

          // If user skipped email (null), go to explore-more
          if (!email) {
            console.log("[lead-email next] Email was skipped, going to explore-more");
            state.isRejectionFlow = false;
            state.nextStepAfterEmail = "explore-more";
            return "explore-more";
          }

          // If email was provided, go to pincode
          var nextStep = state.nextStepAfterEmail || "lead-pincode";
          state.isRejectionFlow = false;
          state.nextStepAfterEmail = "explore-more";
          console.log("[lead-email next] Email was provided, going to:", nextStep);
          return nextStep;
        }
        return "lead-pincode";
      },
    },
    {
      id: "lead-pincode",
      kind: "input",
      bot: function () {
        return "In case you want our dealer to reach you, please share your Pin code or Zip code.";
      },
      placeholder: "Pin code or Zip code",
      validate: pincodeValidate,
      optional: true,
      next: function () {
        var pincode = state.answers["lead-pincode"];
        console.log("[lead-pincode next] skipDealerSteps:", state.skipDealerSteps, "pincode:", pincode);

        if (state.skipDealerSteps) {
          state.skipDealerSteps = false;
          // In rejection flow, still show dealer info based on pincode
          if (pincode) {
            var trimmed = pincode.trim();
            if (/^\d{6}$/.test(trimmed)) {
              console.log("[lead-pincode next] Rejection flow - Indian pincode, showing dealer-notification");
              return "dealer-notification";
            } else {
              console.log("[lead-pincode next] Rejection flow - International pincode, showing international-dealer");
              return "international-dealer";
            }
          } else {
            console.log("[lead-pincode next] Rejection flow - No pincode, showing dealer-locator");
            return "dealer-locator";
          }
        }

        // Normal flow (when pump was found)
        if (pincode) {
          var trimmed = pincode.trim();
          if (/^\d{6}$/.test(trimmed)) {
            console.log("[lead-pincode next] Indian pincode, showing dealer-notification");
            return "dealer-notification";
          } else {
            console.log("[lead-pincode next] International pincode, showing international-dealer");
            return "international-dealer";
          }
        } else {
          console.log("[lead-pincode next] No pincode, showing dealer-locator");
          return "dealer-locator";
        }
      },
    },
    {
      id: "dealer-notification",
      kind: "text",
      bot: function () {
        return "Your requirement and mail ID has been communicated to our dealer, who will contact you for further support.";
      },
      next: function () {
        return "explore-more";
      },
    },
    {
      id: "dealer-locator",
      kind: "text",
      bot: function () {
        return 'You can find nearest dealer through our website :- <a href="https://wilo.com/in/en/About-Us/Contact-Us/Dealer-Locator/" target="_blank">Dealer Locator | Wilo</a>';
      },
      next: function () {
        return "explore-more";
      },
    },
    {
      id: "international-dealer",
      kind: "text",
      bot: function () {
        return 'As you are out of India, please visit our website to locate the nearest Wilo office <a href="https://wilo.com/en/Company/International/" target="_blank">Worldwide | Wilo</a>';
      },
      next: function () {
        return "explore-more";
      },
    },
    {
      id: "thank-you",
      kind: "final",
      bot: function () {
        return "";
      },
      followUp: function () {
        return [
          {
            kind: "html",
            html:
              "<strong>🙏 Thank you for visiting Wilo!</strong><br><br>" +
              "We appreciate your interest in our products and services. If you need any further assistance, our support team is ready to help. 😊<br><br>" +
              "<strong>Contact Support:</strong><br>" +
              '📧 <a href="mailto:sales@wilo.com">sales@wilo.com</a><br>' +
              '🌐 <a href="https://wilo.com/in/en/Dealers/" target="_blank" rel="noopener noreferrer">https://wilo.com/in/en/Dealers/</a>',
          },
        ];
      },
      next: function () {
        return null;
      },
    },
    {
      id: "explore-more",
      kind: "input",
      bot: function () {
        return "Do you want to explore more pump that we have? (yes/no)";
      },
      placeholder: "Type yes or no",
      validate: function (value) {
        var trimmed = value.toLowerCase().trim();
        if (trimmed === "yes" || trimmed === "no") return null;
        return "Please respond with either 'Yes' or 'No'.";
      },
      next: function () {
        var answer = state.answers["explore-more"];
        return answer && answer.toLowerCase().trim() === "yes" ? "application" : "thank-you";
      },
    },
    {
      id: "final-goodbye",
      kind: "options",
      bot: function () {
        return "Would you like to explore our other pump solutions?";
      },
      options: [
        {
          label: "Pressure Boosting",
          description: "Enjoy strong and consistent water pressure.",
          value: "pressure-boosting",
          icon: "./Pressure Boosting.png",
        },
        {
          label: "Heating Circuit",
          description: "Keep every room comfortably warm.",
          value: "heating-circuits",
          icon: "./Heating Circuits.png",
        },
        {
          label: "Domestic Hot Water",
          description: "Get hot water quickly when you need it.",
          value: "domestic-hot-water",
          icon: "./Domestic Hot Water.png",
        },
        {
          label: "Dewatering",
          description: "Remove unwanted water efficiently.",
          value: "dewatering",
          icon: "./Dewatering.png",
        },
        {
          label: "Borewell to Overhead Tank",
          description: "Supply water from your borewell to the storage tank.",
          value: "water-transfer",
          icon: "./Borewell to Overhead tank.png",
        },
        {
          label: "Bottom Tank to Overhead Tank",
          description: "Transfer water from the ground tank to the rooftop tank.",
          value: "tank-filling",
          icon: "./From Bottom tank to Overhead tank.png",
        },
      ],
      next: function (value) {
        if (value === "water-transfer") return "__dynamic__water_transfer";
        if (value === "tank-filling") return "__dynamic__tank_filling";
        if (value === "pressure-boosting") return "__dynamic__pressure_boosting";
        if (value === "dewatering") return "__dynamic__dewatering";
        if (value === "heating-circuits") return "__dynamic__heat_circulation";
        if (value === "domestic-hot-water") return "__dynamic__domestic_hot_water";
        return "final-goodbye";
      },
    },
  ];

  function getStep(id) {
    for (var i = 0; i < FLOW.length; i++) {
      if (FLOW[i].id === id) return FLOW[i];
    }
    throw new Error("Unknown conversation step: " + id);
  }

  // ---------------------------------------------------------------------
  // Conversation state (mutated in place, then re-rendered)
  // ---------------------------------------------------------------------
  var messageCounter = 0;
  function nextMessageId() {
    messageCounter += 1;
    return "msg-" + messageCounter;
  }

  function timestamp() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  var state = {
    messages: [],
    answers: {},
    currentStepId: null,
    awaitingKind: null,
    inputError: null,
    virtualOptions: null, // [{ label, onSelect }] - used for backend-driven branches
    useCaseSlug: null, // "water_transfer" | "tank_filling" while the dynamic loop is active
    dynamicAnswers: {}, // accumulated answers fed to next_question, then to recommend as-is
    clarificationAttempts: {}, // question_key -> retry count, sent back to /answer as clarification_attempts
    clarificationUserInput: {}, // question_key -> original user input that triggered clarification
    clarificationSuggestedValues: {}, // question_key -> suggested_value from needs_clarification, sent back as pending_suggestion
    currentQuestion: null, // last { key, prompt, unit, optional } from next_question
    lastRecommendation: null, // the ok recommendation, kept around for /explain_model follow-ups
    selectedPump: null, // { recommendation, tierLabel } when user selects a pump
    isRejectionFlow: false, // true when pump not found or question fails
    nextStepAfterEmail: "explore-more", // where to go after email in rejection flow
    nextStepAfterPincode: "explore-more", // where to go after pincode in rejection flow (explore-more or final-goodbye)
    skipDealerSteps: false, // true in rejection flow to skip dealer-notification/international-dealer steps
    pumpSelectionPending: null, // { recommendation, tierLabel } - holds pump data awaiting confirmation
    pincodeSubmitted: false, // true after pincode is submitted - prevents pump changes in same use case
    pincodeSubmittedUseCase: null, // the use case where pincode was submitted - lock only applies to same use case
  };

  function addBotMessage(text) {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), text: text, kind: "text" });
  }
  function addBotHtmlMessage(html) {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), html: html, kind: "html" });
  }
  /** Adds a step's main bot message, then any followUp messages (text or
   * html) it defines, e.g. the multi-message sign-off on "thank-you". */
  function addStepMessages(step, answers) {
    var botMsg = step.bot(answers);
    if (botMsg.trim()) {
      if ((step.id === "thank-you" && state.selectedPump) || step.id === "dealer-locator") {
        addBotHtmlMessage(botMsg);
      } else {
        addBotMessage(botMsg);
      }
    }
    if (!step.followUp) return;
    step.followUp(answers).forEach(function (msg) {
      if (msg.kind === "html") addBotHtmlMessage(msg.html);
      else addBotMessage(msg.text);
    });
  }
  function addUserMessage(text) {
    state.messages.push({ id: nextMessageId(), role: "user", timestamp: timestamp(), text: text, kind: "text" });
  }
  function addRecommendationMessage(recommendation, tiedAlternatives) {
    state.messages.push({
      id: nextMessageId(),
      role: "bot",
      timestamp: timestamp(),
      kind: "recommendation",
      recommendation: recommendation,
      tiedAlternatives: tiedAlternatives || [],
    });
  }

  function initConversation() {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), kind: "welcome" });
    var first = FLOW[0];
    addBotMessage(first.bot({}));
    state.currentStepId = first.id;
    state.awaitingKind = first.kind;
  }

  function restartConversation() {
    state.messages = [];
    state.answers = {};
    state.currentStepId = null;
    state.awaitingKind = null;
    state.inputError = null;
    state.virtualOptions = null;
    state.useCaseSlug = null;
    state.dynamicAnswers = {};
    state.clarificationAttempts = {};
    state.clarificationUserInput = {};
    state.clarificationSuggestedValues = {};
    state.currentQuestion = null;
    state.lastRecommendation = null;
    state.selectedPump = null;
    state.isRejectionFlow = false;
    state.nextStepAfterPincode = "explore-more";
    state.skipDealerSteps = false;
    state.pincodeSubmitted = false;
    state.pincodeSubmittedUseCase = null;
    initConversation();
    render();
  }

  function jumpToStep(stepId) {
    var step = getStep(stepId);
    state.virtualOptions = null;
    state.inputError = null;
    addStepMessages(step, state.answers);
    state.currentStepId = step.id;
    state.awaitingKind = step.kind;

    if (step.kind === "text" && (step.id === "dealer-notification" || step.id === "dealer-locator" || step.id === "international-dealer")) {
      setTimeout(function () {
        var nextStepId = step.next(state.answers);
        if (nextStepId) {
          jumpToStep(nextStepId);
          render();
        }
      }, 100);
    }
  }

  function showUnreachableBackendError(retryFn) {
    addBotMessage(
      "I couldn't reach the recommendation service. Make sure the backend is running at " +
        API_BASE_URL +
        " and try again."
    );
    state.awaitingKind = "options";
    state.virtualOptions = [
      {
        label: "Retry",
        icon: "🔁",
        onSelect: function () {
          addUserMessage("Retry");
          return retryFn();
        },
      },
    ];
    render();
  }

  async function sendRejectionLeadToAPI() {
    console.log("[Rejection Lead API] ===== SENDING REJECTION LEAD START =====");
    console.log("[Rejection Lead API] isRejectionFlow:", state.isRejectionFlow);
    console.log("[Rejection Lead API] useCaseSlug:", state.useCaseSlug);

    var email = state.answers["lead-email"] || "";
    var pincode = state.answers["lead-pincode"] || "";

    if (!email && !pincode) {
      console.log("[Rejection Lead API] No email or pincode provided, skipping API call");
      return;
    }

    var applicationMap = {
      "water_transfer": "Water Extraction From Borewell",
      "tank_filling": "Transfer of water from a ground level reservoir to an Overhead tank",
      "pressure_boosting": "Pressure Boosting",
      "dewatering": "Dewatering",
      "heat_circulation": "Heat Circuits Application",
      "domestic_hot_water": "Domestic Hot Water",
    };

    var payload = {
      data: {
        userDetails: {
          email: email,
          pincode: pincode,
          name: state.answers["lead-name"] || "",
        },
        rejectionDetails: {
          application: applicationMap[state.useCaseSlug] || "Unknown",
          noSuitablePumpFound: true,
          answeredQuestions: state.dynamicAnswers,
        },
      },
    };

    try {
      console.log("[Rejection Lead API] Sending rejection lead to backend...");
      console.log("[Rejection Lead API] Payload:", JSON.stringify(payload, null, 2));

      var res = await fetch(API_BASE_URL + "/send-rejection-lead", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      var data = await res.json();
      console.log("[Rejection Lead API] Response Status:", res.status);
      console.log("[Rejection Lead API] Response Data:", JSON.stringify(data, null, 2));

      if (res.ok) {
        console.log("[Rejection Lead API] Success! Rejection lead has been captured.");
      } else {
        console.error("[Rejection Lead API] Error - Status:", res.status, "Details:", data);
      }

      return data;
    } catch (err) {
      console.error("[Rejection Lead API] Error sending rejection lead:", err);
      console.error("[Rejection Lead API] Error details:", err.message);
    }
  }

  async function sendPumpDataToAPI() {
    if (!state.selectedPump) {
      console.log("[Pump Data API] No pump selected, skipping API call");
      return;
    }

    var pump = state.selectedPump.recommendation;
    var details = pump.details || {};
    var contact = state.answers["lead-contact"] || "";

    // Map application type based on use case
    var applicationMap = {
      "water_transfer": "Water Extraction From Borewell",
      "tank_filling": "Transfer of water from a ground level reservoir to an Overhead tank",
      "pressure_boosting": "Pressure Boosting",
      "dewatering": "Dewatering",
      "heat_circulation": "Heat Circuits Application",
      "domestic_hot_water": "Domestic Hot Water",
    };

    // Determine if initial contact is email or phone
    var isEmail = /^\S+@\S+\.\S+$/.test(contact);
    var userDetails = {
      pincode: state.answers["lead-pincode"] || "",
      name: state.answers["lead-name"] || "",
      contactNumber: isEmail ? "" : contact,
      email: isEmail ? contact : (state.answers["lead-email"] || ""),
    };

    var headUnit = details.head_unit || state.dynamicAnswers[unitFieldNameFor("head")] || "m";
    var headUnitLabel = headUnit === "ft" ? "feet" : (headUnit === "m" ? "meter" : headUnit);
    var powerUnit = details.power_unit || "HP";
    var flowUnit = details.flow_unit || "lpm";

    console.log("[Pump Data API] head_unit debug:", {
      details_head_unit: details.head_unit,
      dynamicAnswers_head_unit: state.dynamicAnswers[unitFieldNameFor("head")],
      final_headUnit: headUnit,
      headUnitLabel: headUnitLabel
    });

    var payload = {
      data: {
        userDetails: userDetails,
        searchDetails: {
          application: applicationMap[state.useCaseSlug] || "Unknown",
          RequiredHead: details.target_head ? Math.round(details.target_head) + " " + headUnitLabel : "",
          RequiredPower: state.dynamicAnswers.motor_power_hp ? state.dynamicAnswers.motor_power_hp + " " + powerUnit : "",
        },
        selectedPump: {
          pumpModel: pump.model_name || "",
          articleNo: pump.art_no ? String(pump.art_no) : "",
          motorRating: details.hp ? details.hp + " " + powerUnit : "",
          selectedHead: details.matched_head ? Math.round(details.matched_head) + " " + headUnitLabel : (details.specs && details.specs.head ? details.specs.head : ""),
          selectedFlow: details.flow ? details.flow + " " + flowUnit : (details.specs && details.specs.flow ? details.specs.flow : ""),
          fluidTemperature: details.specs && details.specs.fluid_temp ? details.specs.fluid_temp : "",
          connection: details.specs && details.specs.connection ? details.specs.connection : "",
          features: pump.features ? pump.features.join(", ") : "",
        },
      },
    };

    try {
      console.log("[Pump Data API] Sending pump data to backend...");
      console.log("[Pump Data API] Payload:", JSON.stringify(payload, null, 2));

      var res = await fetch(API_BASE_URL + "/send-pump-data", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      var data = await res.json();
      console.log("[Pump Data API] Response Status:", res.status);
      console.log("[Pump Data API] Response Data:", JSON.stringify(data, null, 2));

      if (res.ok) {
        console.log("[Pump Data API] Success! Pump data has been shared with dealer.");
      } else {
        console.error("[Pump Data API] Error - Status:", res.status, "Details:", data);
      }

      return data;
    } catch (err) {
      console.error("[Pump Data API] Error sending pump data:", err);
      console.error("[Pump Data API] Error details:", err.message);
    }
  }


  /** Calls the recommendation backend for the active use case and handles
   * ok / confirmation_required / rejected / network-error. */
  async function runRecommendation(confirmOversize) {
    state.awaitingKind = "loading";
    state.virtualOptions = null;
    addBotMessage("Let me find the best pump for you...");
    render();

    var payload = Object.assign({}, state.dynamicAnswers);
    if (typeof confirmOversize === "boolean") payload.confirm_oversize = confirmOversize;

    if (state.useCaseSlug === "water_transfer") {
      if (!payload.num_floors) payload.num_floors = 0;
      if (!payload.confirm_oversize) payload.confirm_oversize = false;
    }

    var data;

    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();

    } catch (err) {
      console.error("[runRecommendation] fetch error:", err);
      showUnreachableBackendError(function () {
        return runRecommendation(confirmOversize);
      });
      return;
    }

    console.log("[runRecommendation] ===== RECOMMENDATION REQUEST START =====");
    console.log("[runRecommendation] use case slug:", state.useCaseSlug);
    console.log("[runRecommendation] payload sent to /recommend:", JSON.stringify(payload, null, 2));
    console.log("[runRecommendation] full response received:", JSON.stringify(data, null, 2));
    console.log("[runRecommendation] response status:", data.status);

    if (data.status === "ok") {
      console.log("[runRecommendation] STATUS: OK - Showing recommendation");
      addBotMessage("Based on what you shared, here's wilo solution to meet your requirements.");
      var tiedAlts = (data.recommendation && data.recommendation.tied_alternatives) || [];
      if (data.premium_recommendation) {
        tiedAlts = [data.premium_recommendation].concat(tiedAlts);
      }
      addRecommendationMessage(data.recommendation, tiedAlts);
      state.lastRecommendation = data.recommendation;
      render();
      return;
    }

    if (data.status === "confirmation_required") {
      console.log("[runRecommendation] STATUS: CONFIRMATION_REQUIRED - Pump may be oversized");
      addBotMessage(data.message || "This selection looks oversized for your setup. Do you want to proceed anyway?");
      state.awaitingKind = "text";
      state.confirmationHandler = function (userInput) {
        var normalized = userInput.toLowerCase().trim();
        if (normalized === "yes" || normalized === "y") {
          addUserMessage(userInput);
          return runRecommendation(true);
        } else if (normalized === "no" || normalized === "n") {
          addUserMessage(userInput);
          addBotMessage("I understand. Let me show you pumps from other applications that might work better for your setup.");

          state.confirmationHandler = null;
          state.awaitingKind = "options";
          state.virtualOptions = [
            {
              label: "Pressure Boosting",
              icon: "./Pressure Boosting.png",
              onSelect: function () {
                addUserMessage("Pressure Boosting");
                state.virtualOptions = null;
                state.useCaseSlug = "pressure_boosting";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
            {
              label: "Heating Circuit",
              icon: "./Heating Circuits.png",
              onSelect: function () {
                addUserMessage("Heating Circuit");
                state.virtualOptions = null;
                state.useCaseSlug = "heat_circulation";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
            {
              label: "Domestic Hot Water",
              icon: "./Domestic Hot Water.png",
              onSelect: function () {
                addUserMessage("Domestic Hot Water");
                state.virtualOptions = null;
                state.useCaseSlug = "domestic_hot_water";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
            {
              label: "Dewatering",
              icon: "./Dewatering.png",
              onSelect: function () {
                addUserMessage("Dewatering");
                state.virtualOptions = null;
                state.useCaseSlug = "dewatering";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
            {
              label: "Borewell to Overhead Tank",
              icon: "./Borewell to Overhead tank.png",
              onSelect: function () {
                addUserMessage("Borewell to Overhead Tank");
                state.virtualOptions = null;
                state.useCaseSlug = "water_transfer";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
            {
              label: "Bottom Tank to Overhead Tank",
              icon: "./From Bottom tank to Overhead tank.png",
              onSelect: function () {
                addUserMessage("Bottom Tank to Overhead Tank");
                state.virtualOptions = null;
                state.useCaseSlug = "tank_filling";
                state.dynamicAnswers = {};
                state.clarificationAttempts = {};
                state.clarificationUserInput = {};
                state.clarificationSuggestedValues = {};
                state.currentQuestion = null;
                fetchNextQuestion().then(render);
              },
            },
          ];
          render();
          return Promise.resolve();
        } else {
          addBotMessage("Please type 'yes' or 'no' to proceed.");
          return Promise.resolve();
        }
      };
      render();
      return;
    }

    // status === "rejected" (or anything unrecognized)
    console.log("[runRecommendation] STATUS: REJECTED or UNRECOGNIZED");
    console.log("[runRecommendation] Reason: The backend rejected this requirement");
    console.log("[runRecommendation] Backend response details:", JSON.stringify(data, null, 2));
    console.warn("[runRecommendation] Showing rejection message and asking for email contact");
    var rejectionMsg = 'For this requirement you need a special pump, please provide your email ID so we can contact you, or visit our website to locate the nearest dealer 📧 <a href="mailto:sales@wilo.com" target="_blank">sales@wilo.com</a> 🌐 <a href="https://wilo.com/in/en/Dealers/" target="_blank">https://wilo.com/in/en/Dealers/</a>';
    addBotHtmlMessage(rejectionMsg);
    state.isRejectionFlow = true;
    state.nextStepAfterEmail = "lead-pincode";
    state.skipDealerSteps = true;
    jumpToStep("lead-email");
    console.log("[runRecommendation] ===== REJECTION FLOW INITIATED =====");
    render();
  }

  /** Asks the backend what to ask next for the active use case; once it
   * returns question: null, moves on to /recommend. */
  async function fetchNextQuestion(confirmationMessage) {
    console.log("[fetchNextQuestion] ===== FETCH NEXT QUESTION START =====");
    console.log("[fetchNextQuestion] use case slug:", state.useCaseSlug);
    console.log("[fetchNextQuestion] current answers:", JSON.stringify(state.dynamicAnswers, null, 2));

    state.awaitingKind = "loading";
    state.virtualOptions = null;

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/next_question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: state.dynamicAnswers }),
      });
      data = await res.json();
    } catch (err) {
      console.error("[fetchNextQuestion] fetch error:", err);
      render();
      showUnreachableBackendError(function () { return fetchNextQuestion(confirmationMessage); });
      return;
    }

    console.log("[fetchNextQuestion] response from backend:", JSON.stringify(data, null, 2));

    if (data.question) {
      console.log("[fetchNextQuestion] NEXT QUESTION AVAILABLE");
      console.log("[fetchNextQuestion] question key:", data.question.key);
      console.log("[fetchNextQuestion] question prompt:", data.question.prompt);
      console.log("[fetchNextQuestion] question optional:", data.question.optional);
      console.log("[fetchNextQuestion] question unit:", data.question.unit);
      state.currentQuestion = data.question;

      var messageText = data.question.prompt;
      if (confirmationMessage) {
        messageText = confirmationMessage + "\n" + data.question.prompt;
      }

      // Check if this is a categorical question - render as card options
      if ((state.useCaseSlug === "heat_circulation" || state.useCaseSlug === "water_transfer" || state.useCaseSlug === "tank_filling") && CATEGORY_QUESTION_KEYS.indexOf(data.question.key) !== -1) {
        console.log("[fetchNextQuestion] CATEGORICAL QUESTION - Rendering as card options");
        // Remove the redundant option list from the question prompt for categorical questions
        var questionOnly = data.question.prompt.split("?")[0] + "?";
        messageText = confirmationMessage ? confirmationMessage + "\n" + questionOnly : questionOnly;
        addBotMessage(messageText);
        var categoryOptions = [];

        // Map category values to display labels and icons
        var categoryLabels = {
          "ufh": "Underfloor Heating (UFH)",
          "radiators": "Radiators",
          "delivery_type": "Delivery Type",
          "inside_or_outside": "Inside or Outside",
          "horizontal_or_vertical": "Horizontal or Vertical",
          "ground_floor": "Ground Floor",
          "elevated_tank": "Elevated Tank",
          "inside": "Inside",
          "outside": "Outside",
          "horizontal": "Horizontal",
          "vertical": "Vertical"
        };

        var categoryIcons = {
          "ufh": "🔥",
          "radiators": "🌡️",
          "delivery_type": "⬆️",
          "ground_floor": "📍",
          "elevated_tank": "🏢",
          "inside": "🏠",
          "outside": "🌳",
          "horizontal": "↔️",
          "vertical": "↕️"
        };

        // Build options from the question or known categories
        var optionValues = [];
        if (data.question.key === "heating_system") {
          optionValues = ["ufh", "radiators"];
        } else if (data.question.key === "delivery_type") {
          optionValues = ["ground_floor", "elevated_tank"];
        } else if (data.question.key === "inside_or_outside") {
          optionValues = ["inside", "outside"];
        } else if (data.question.key === "horizontal_or_vertical") {
          optionValues = ["horizontal", "vertical"];
        }

        optionValues.forEach(function(value) {
          categoryOptions.push({
            label: categoryLabels[value] || value,
            value: value,
            icon: categoryIcons[value] || "•",
            onSelect: function() {
              submitCategoryAnswer(data.question, value);
            }
          });
        });

        state.awaitingKind = "options";
        state.virtualOptions = categoryOptions;
      } else {
        addBotMessage(messageText);
        state.awaitingKind = "dynamic-input";
      }

      render();
      return;
    }

    if (data.detail) {
      console.log("[fetchNextQuestion] ERROR DETAIL FOUND:", data.detail);
      addBotMessage("Sorry, something went wrong with the recommendation engine. Please try again.");
      jumpToStep("application");
      render();
      return;
    }

    console.log("[fetchNextQuestion] NO MORE QUESTIONS - Moving to /recommend");
    if (confirmationMessage) {
      addBotMessage(confirmationMessage);
    }

    render();
    return runRecommendation();
  }

  /** A required question that comes back "skipped" (or given-up-on) re-prompts
   * the user; an optional one is recorded as null and the loop moves on. */
  async function handleUnansweredQuestion(question) {
    console.log("[handleUnansweredQuestion] ===== UNANSWERED QUESTION START =====");
    console.log("[handleUnansweredQuestion] question key:", question.key);
    console.log("[handleUnansweredQuestion] question prompt:", question.prompt);
    console.log("[handleUnansweredQuestion] question.optional:", question.optional);

    if (!question.optional) {
      console.log("[handleUnansweredQuestion] REQUIRED QUESTION UNANSWERED - Triggering rejection flow");
      console.log("[handleUnansweredQuestion] Reason: User could not answer a required question (backend returned skipped or gave_up)");
      var rejectionMsg = 'For this requirement you need a special pump, please provide your email ID so we can contact you, or visit our website to locate the nearest dealer 📧 <a href="mailto:sales@wilo.com" target="_blank">sales@wilo.com</a> 🌐 <a href="https://wilo.com/in/en/Dealers/" target="_blank">https://wilo.com/in/en/Dealers/</a>';
      addBotHtmlMessage(rejectionMsg);

      state.useCaseSlug = null;
      state.dynamicAnswers = {};
      state.clarificationAttempts = {};
      state.clarificationUserInput = {};
      state.clarificationSuggestedValues = {};
      state.currentQuestion = null;
      state.isRejectionFlow = true;
      state.nextStepAfterEmail = "lead-pincode";
      state.skipDealerSteps = true;
      state.nextStepAfterPincode = "final-goodbye";

      jumpToStep("lead-email");
      console.log("[handleUnansweredQuestion] ===== REJECTION FLOW INITIATED (FROM UNANSWERED QUESTION) =====");
      render();
      return;
    }

    console.log("[handleUnansweredQuestion] OPTIONAL QUESTION SKIPPED - Continuing to next question");
    state.dynamicAnswers[question.key] = null;
    state.currentQuestion = null;
    await fetchNextQuestion();
  }

  /** Sends the user's free-text reply to the backend's fixed-choice parser
   * (ParsedCategory) for questions like inside_or_outside / horizontal_or_vertical. */
  async function submitCategoryAnswer(question, trimmed) {
    console.log("[submitCategoryAnswer] ===== SUBMIT CATEGORY ANSWER START =====");
    console.log("[submitCategoryAnswer] question key:", question.key);
    console.log("[submitCategoryAnswer] user input:", trimmed);

    var payload = { question_key: question.key, user_text: trimmed, answers_so_far: state.dynamicAnswers };
    if (state.clarificationAttempts[question.key]) {
      payload.clarification_attempts = state.clarificationAttempts[question.key];
    }

    console.log("[submitCategoryAnswer] payload to /answer_category:", JSON.stringify(payload, null, 2));

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/answer_category", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      console.error("[submitCategoryAnswer] fetch error:", err);
      showUnreachableBackendError(function () {
        return submitCategoryAnswer(question, trimmed);
      });
      return;
    }

    console.log("[submitCategoryAnswer] response from /answer_category:", JSON.stringify(data, null, 2));

    if (data.needs_clarification || data.edit_not_supported) {
      console.log("[submitCategoryAnswer] NEEDS_CLARIFICATION - Asking for more details");
      state.clarificationAttempts[question.key] = (state.clarificationAttempts[question.key] || 0) + 1;
      addBotMessage(data.clarification_question || "Could you clarify that?");
      state.awaitingKind = "dynamic-input";
      render();
      return;
    }

    if (data.skipped) {
      console.log("[submitCategoryAnswer] SKIPPED - User skipped this category question");
      handleUnansweredQuestion(question);
      return;
    }

    if (data.gave_up) {
      console.log("[submitCategoryAnswer] GAVE_UP - Backend gave up on this category question");
      handleUnansweredQuestion(question);
      return;
    }

    console.log("[submitCategoryAnswer] ACCEPTED - Category accepted:", data.category);
    delete state.clarificationAttempts[question.key];
    state.dynamicAnswers[question.key] = data.category;
    console.log("[submitCategoryAnswer] cumulative answers so far:", JSON.stringify(state.dynamicAnswers, null, 2));
    state.currentQuestion = null;
    await fetchNextQuestion(data.confirmation_message);
  }

  /** Sends the user's free-text reply to the backend's LLM parser (ParsedAnswer)
   * for the current question; loops back on needs_clarification/edit_not_supported without
   * advancing (tracking retries via clarification_attempts), reroutes the value to
   * redirect_key if the user answered a different question, treats gave_up as
   * an unanswered/optional-skip, otherwise records the parsed value (+ unit)
   * and moves to the next question. */
  async function submitFreeTextAnswer(question, trimmed) {
    console.log("[submitFreeTextAnswer] ===== SUBMIT FREE TEXT ANSWER START =====");
    console.log("[submitFreeTextAnswer] question key:", question.key);
    console.log("[submitFreeTextAnswer] user input:", trimmed);

    var userText = trimmed;
    var payload = { question_key: question.key, user_text: userText, answers_so_far: state.dynamicAnswers };

    var pendingSuggestion = state.clarificationSuggestedValues[question.key];
    if (pendingSuggestion !== undefined && pendingSuggestion !== null) {
      payload.pending_suggestion = pendingSuggestion;
    }

    // Also send previous_value + unit if available (for unit corrections after ambiguous answers)
    var previousValue = state.dynamicAnswers[question.key];
    if (previousValue !== undefined && previousValue !== null) {
      payload.previous_value = previousValue;
      var previousUnit = state.dynamicAnswers[unitFieldNameFor(question.key)];
      if (previousUnit !== undefined) payload.previous_unit = previousUnit;
    }
    if (state.clarificationAttempts[question.key]) {
      payload.clarification_attempts = state.clarificationAttempts[question.key];
    }

    console.log("[submitFreeTextAnswer] payload to /answer endpoint:", JSON.stringify(payload, null, 2));

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      console.error("[submitFreeTextAnswer] fetch error:", err);
      showUnreachableBackendError(function () {
        return submitFreeTextAnswer(question, trimmed);
      });
      return;
    }

    console.log("[submitFreeTextAnswer] response from /answer:", JSON.stringify(data, null, 2));

    if (data.needs_clarification || data.edit_not_supported) {
      console.log("[submitFreeTextAnswer] NEEDS_CLARIFICATION - Asking user for more details");
      state.clarificationAttempts[question.key] = (state.clarificationAttempts[question.key] || 0) + 1;
      if (data.suggested_value !== undefined && data.suggested_value !== null) {
        state.clarificationSuggestedValues[question.key] = data.suggested_value;
        console.log("[submitFreeTextAnswer] Stored pending_suggestion:", question.key, "=", data.suggested_value);
      }
      if (data.value !== undefined && data.value !== null) {
        state.dynamicAnswers[question.key] = data.value;
      } else if (data.suggested_value !== undefined && data.suggested_value !== null) {
        state.dynamicAnswers[question.key] = data.suggested_value;
      } else {
        var bareNumberMatch = /^\s*[+-]?\d+(?:\.\d+)?\s*$/.exec(trimmed);
        if (bareNumberMatch) {
          state.dynamicAnswers[question.key] = parseFloat(trimmed);
        }
      }
      if (data.unit) {
        state.dynamicAnswers[unitFieldNameFor(question.key)] = data.unit;
      }
      addBotMessage(data.clarification_question || "Could you clarify that?");
      state.awaitingKind = "dynamic-input";
      render();
      return;
    }
    delete state.clarificationAttempts[question.key];

    if (data.gave_up) {
      console.log("[submitFreeTextAnswer] GAVE_UP - Backend gave up on this question");
      handleUnansweredQuestion(question);
      return;
    }

    if (data.redirect_key) {
      console.log("[submitFreeTextAnswer] REDIRECT_KEY - User answered a different question:", data.redirect_key);
      state.dynamicAnswers[data.redirect_key] = data.value;
      if (data.unit) state.dynamicAnswers[unitFieldNameFor(data.redirect_key)] = data.unit;
      state.currentQuestion = null;
      await fetchNextQuestion();
      return;
    }

    if (data.skipped) {
      console.log("[submitFreeTextAnswer] SKIPPED - User skipped this question");
      handleUnansweredQuestion(question);
      return;
    }

    console.log("[submitFreeTextAnswer] ACCEPTED - Answer accepted by backend");
    state.dynamicAnswers[question.key] = data.value;
    var unit = data.unit || question.unit;
    if (unit) state.dynamicAnswers[unitFieldNameFor(question.key)] = unit;

    console.log("[submitFreeTextAnswer] stored value:", question.key, "=", data.value, unit ? "(unit: " + unit + ")" : "");
    console.log("[submitFreeTextAnswer] cumulative answers so far:", JSON.stringify(state.dynamicAnswers, null, 2));

    delete state.clarificationUserInput[question.key];
    delete state.clarificationAttempts[question.key];
    delete state.clarificationSuggestedValues[question.key];

    state.currentQuestion = null;
    await fetchNextQuestion(data.confirmation_message);
  }

  function submitDynamicAnswer(rawValue) {
    var question = state.currentQuestion;
    if (!question) return;
    var trimmed = rawValue.trim();
    if (!trimmed) return;

    // Prevent duplicate submissions while processing
    if (state.awaitingKind === "loading") {
      console.log("[submitDynamicAnswer] Already loading, ignoring duplicate submission");
      return;
    }

    addUserMessage(trimmed);
    state.inputError = null;
    state.awaitingKind = "loading";
    render();

    if (CATEGORY_QUESTION_KEYS.indexOf(question.key) !== -1) {
      return submitCategoryAnswer(question, trimmed);
    }
    return submitFreeTextAnswer(question, trimmed);
  }

  /** Advances through fixed steps, stopping at the next question, a dynamic
   * question-flow kickoff, or the end. */
  function advance(fromStep, answerValue) {
    var nextId = fromStep.next ? fromStep.next(answerValue, state.answers) : null;
    if (!nextId) {
      state.awaitingKind = "final";
      return null;
    }
    if (nextId.indexOf("__dynamic__") === 0) {
      state.useCaseSlug = nextId.slice("__dynamic__".length);
      state.dynamicAnswers = {};
      state.clarificationAttempts = {};
      state.clarificationUserInput = {};
      state.clarificationSuggestedValues = {};
      state.currentQuestion = null;

      // Reset pincode flags when exploring new application - allows fresh pump selection with new parameters
      state.pincodeSubmitted = false;
      state.pincodeSubmittedUseCase = null;

      // Add confirmation message with selected application
      var appName = "";
      if (state.useCaseSlug === "water_transfer") appName = "Borewell to Overhead tank";
      else if (state.useCaseSlug === "tank_filling") appName = "From Bottom tank to Overhead tank";
      else if (state.useCaseSlug === "pressure_boosting") appName = "Pressure Boosting";
      else if (state.useCaseSlug === "dewatering") appName = "Dewatering";
      else if (state.useCaseSlug === "heat_circulation") appName = "Heat Circuits Application";
      else if (state.useCaseSlug === "domestic_hot_water") appName = "Domestic Hot Water";

      addBotHtmlMessage("Hi There, you have selected application as<br><strong style='color: #009C82;'>" + appName + "</strong>");

      // Remove greeting message after application selection
      if (state.messages.length > 1) {
        state.messages.splice(1, 1);
      }

      return fetchNextQuestion();
    }
    var nextStep = getStep(nextId);

    // Use jumpToStep for dealer steps to handle auto-advance to explore-more
    if (nextStep.id === "dealer-notification" || nextStep.id === "dealer-locator" || nextStep.id === "international-dealer") {
      return jumpToStep(nextId);
    }

    addStepMessages(nextStep, state.answers);
    state.currentStepId = nextStep.id;
    state.awaitingKind = nextStep.kind;
    state.inputError = null;

    // If this step is final but has a next function, continue to the next step
    if (nextStep.kind === "final" && nextStep.next) {
      var followUpId = nextStep.next(answerValue, state.answers);
      if (followUpId) {
        var followUpStep = getStep(followUpId);
        addStepMessages(followUpStep, state.answers);
        state.currentStepId = followUpStep.id;
        state.awaitingKind = followUpStep.kind;
      }
    }
    return null;
  }

  function submitOption(value, label) {
    if (state.virtualOptions) return; // handled via chip's own onSelect
    var step = getStep(state.currentStepId);
    if (step.kind !== "options") return;
    state.answers[step.id] = value;
    
    // Don't show user message for initial application selection
    if (step.id !== "application") {
      addUserMessage(label);
    }
    
    advance(step, value);
    render();
  }

  function submitText(rawValue) {
    var step = getStep(state.currentStepId);
    if (step.kind !== "input") return;
    var trimmed = rawValue.trim();
    if (!trimmed) return;

    // Check if user wants to skip an optional field
    var isSkipKeyword = /^(skip|no|nope|don't|dont|decline|pass)$/i.test(trimmed);
    var isOptional = typeof step.optional === "function" ? step.optional() : step.optional;
    if (isOptional && isSkipKeyword) {
      console.log("[submitText] User skipped optional field:", step.id);
      state.answers[step.id] = null;
      addUserMessage(trimmed);
      advance(step, null);
      render();
      return;
    }

    var error = step.validate ? step.validate(trimmed) : null;
    if (error) {
      addUserMessage(trimmed);
      addBotMessage(error);
      render();
      return;
    }

    var cleanValue = trimmed;
    if (step.id === "lead-pincode") {
      cleanValue = trimmed.replace(/\s/g, "");
    }
    state.answers[step.id] = cleanValue;
    addUserMessage(trimmed);

    // Send data to API when pincode is submitted
    if (step.id === "lead-pincode") {
      state.pincodeSubmitted = true;
      state.pincodeSubmittedUseCase = state.useCaseSlug;
      if (state.selectedPump) {
        // Normal flow: pump was found and selected
        console.log("[submitText] Sending pump data to API");
        sendPumpDataToAPI();
      } else if (state.isRejectionFlow) {
        // Rejection flow: no pump found
        console.log("[submitText] Sending rejection lead data to API");
        sendRejectionLeadToAPI();
      }
    }

    advance(step, cleanValue);
    render();
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------
  var el = {};

  function mascotImage() {
    var img = document.createElement("img");
    img.className = "mascot";
    img.src = "./logo.png";
    img.alt = "Wilo Pumps Selection Chatbot logo";
    return img;
  }

  function buildWelcomeCard() {
    var card = document.createElement("div");
    card.className = "welcome-card";

    var textWrap = document.createElement("div");
    textWrap.className = "welcome-text";

    var greet = document.createElement("p");
    greet.className = "greet";
    greet.innerHTML = "<strong style='font-size: 16px;'>👋 Hi I am <span style='color: #009C82;'>WiWa</span>!</strong>";

    var line2 = document.createElement("p");
    line2.innerHTML = "<span style='color: #009C82; font-weight: bold;'>Wi</span>lo <span style='color: #009C82; font-weight: bold;'>Wa</span>rrior AI pump tool";
    line2.className = "line2-text";

    var message = document.createElement("p");
    message.textContent = "Let me know your application needs to suggest the best solution.";
    message.className = "application-message";

    textWrap.appendChild(greet);
    textWrap.appendChild(line2);
    textWrap.appendChild(message);

    card.appendChild(textWrap);
    card.appendChild(mascotImage());
    return card;
  }

  var PUMP_ICON_SVG =
    '<svg viewBox="0 0 64 64" width="40" height="40" aria-hidden="true">' +
    '<rect x="4" y="24" width="28" height="18" rx="4" fill="#3f8f7f" />' +
    '<rect x="10" y="30" width="6" height="6" fill="#e3f3ef" />' +
    '<rect x="20" y="30" width="6" height="6" fill="#e3f3ef" />' +
    '<circle cx="44" cy="30" r="13" fill="#2f6f62" />' +
    '<circle cx="44" cy="30" r="7" fill="#e3f3ef" />' +
    '<rect x="42" y="10" width="4" height="14" fill="#2f6f62" />' +
    '<rect x="2" y="42" width="60" height="4" rx="2" fill="#2f6f62" />' +
    "</svg>";

  var LIST_ICON_SVG =
    '<svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" style="vertical-align:-2px;margin-right:6px;">' +
    '<circle cx="2.5" cy="4" r="1.5" fill="#fff" />' +
    '<circle cx="2.5" cy="10" r="1.5" fill="#fff" />' +
    '<circle cx="2.5" cy="16" r="1.5" fill="#fff" />' +
    '<rect x="6" y="3" width="13" height="2" rx="1" fill="#fff" />' +
    '<rect x="6" y="9" width="13" height="2" rx="1" fill="#fff" />' +
    '<rect x="6" y="15" width="13" height="2" rx="1" fill="#fff" />' +
    "</svg>";

  function formatPhaseValue(raw) {
    var match = String(raw).match(/(\d+)/);
    return match ? match[1] + " Phase" : prettifyKey(String(raw));
  }

  function appendUnitIfPlainNumber(value, unit) {
    var text = formatDetailValue(value);
    return /^-?[\d.,]+$/.test(String(value)) && unit ? text + " " + unit : text;
  }

  // Backend "details" fields are internal/engineering data (spec sheet names,
  // matching-target values, etc). Only these customer-relevant fields are
  // shown on the recommendation card; anything else is left out on purpose.
  var DETAIL_DISPLAY_RULES = [
    {
      test: function (key) {
        return /^flow$/i.test(key);
      },
      label: "Flow",
      format: function (value, unit) {
        return appendUnitIfPlainNumber(value, unit || "lpm");
      },
    },
    {
      test: function (key) {
        return /matched_head/i.test(key);
      },
      label: "Head",
      format: function (value, unit) {
        return appendUnitIfPlainNumber(value, unit);
      },
    },
    {
      test: function (key) {
        return /^hp$/i.test(key) || /motor/i.test(key) || /power/i.test(key);
      },
      label: "Motor Power",
      format: function (value, unit) {
        return appendUnitIfPlainNumber(value, unit || "HP");
      },
    },
  ];

  // The "View Pump Details" modal shows more than the summary card: every
  // detail field the backend returns except internal ones (spec sheet name,
  // the raw curve array, which gets its own chart instead of a text row).
  var TECHNICAL_DETAIL_BLACKLIST = ["sheet", "performance_curve", "head_unit", "target_head", "phase", "required_flow", "flow_unit", "heating_system", "tier", "specs", "area", "area_unit", "num_usage_points"];
  var TECHNICAL_DETAIL_RULES = DETAIL_DISPLAY_RULES.concat([
    {
      test: function (key) {
        return /target/i.test(key) && /head/i.test(key);
      },
      label: "Target Head",
      format: function (value, unit) {
        return appendUnitIfPlainNumber(value, unit || "m");
      },
    },
    {
      test: function (key) {
        return /^matched.*head/i.test(key);
      },
      label: "Matched Head",
      format: function (value, unit) {
        return appendUnitIfPlainNumber(value, unit || "m");
      },
    },
  ]);

  function buildTechnicalPointsRows(recommendation) {
    var details = recommendation.details || {};
    var rows = [];
    var processedKeys = new Set();

    // Check if specs are nested (new format for heat_circulation and domestic_hot_water)
    var specs = details.specs || {};

    // Display specs from the new nested format
    if (Object.keys(specs).length > 0) {
      var specLabels = {
        "flow": "Flow Rate",
        "head": "Head",
        "fluid_temp": "Fluid Temperature",
        "connection": "Connection"
      };
      Object.keys(specs).forEach(function (key) {
        if (specs[key]) {
          rows.push({
            label: specLabels[key] || prettifyKey(key),
            value: specs[key]
          });
          processedKeys.add(key);
        }
      });
    }

    var displayOrder = ["flow", "head", "hp", "art_no"];

    displayOrder.forEach(function (key) {
      if (key === "art_no") {
        if (recommendation.art_no != null) {
          rows.push({ label: "Article No.", value: String(recommendation.art_no) });
        }
        processedKeys.add("art_no");
        return;
      }

      var matchingKey;
      if (key === "flow") {
        matchingKey = "flow";
      } else if (key === "head") {
        matchingKey = "matched_head";
      } else if (key === "hp") {
        matchingKey = Object.keys(details).find(function (k) {
          return /^hp$/i.test(k) || /motor/i.test(k) || /power/i.test(k);
        });
      }

      if (matchingKey && details[matchingKey] != null && TECHNICAL_DETAIL_BLACKLIST.indexOf(matchingKey) === -1) {
        var value = details[matchingKey];
        if (value !== "") {
          var rule = TECHNICAL_DETAIL_RULES.find(function (r) {
            return r.test(matchingKey);
          });
          var unit = null;
          if (rule) {
            if (/head/i.test(rule.label)) {
              unit = details.head_unit || state.dynamicAnswers[unitFieldNameFor("head")] || "m";
            } else if (/flow/i.test(rule.label)) {
              unit = details.flow_unit || "lpm";
            } else if (/power|motor/i.test(rule.label)) {
              unit = details.power_unit || "HP";
            } else if (/fill.*time/i.test(rule.label)) {
              unit = details.fill_time_unit || null;
            }
          }
          rows.push({
            label: rule ? rule.label : prettifyKey(matchingKey),
            value: rule ? rule.format(value, unit) : formatDetailValue(value),
          });
          processedKeys.add(matchingKey);
        }
      }
    });

    Object.keys(details).forEach(function (key) {
      if (processedKeys.has(key) || TECHNICAL_DETAIL_BLACKLIST.indexOf(key) !== -1) return;
      var value = details[key];
      if (value == null || value === "") return;
      var rule = TECHNICAL_DETAIL_RULES.find(function (r) {
        return r.test(key);
      });
      var unit = null;
      if (rule) {
        if (/head/i.test(rule.label)) {
          unit = details.head_unit || state.dynamicAnswers[unitFieldNameFor("head")] || "m";
        } else if (/flow/i.test(rule.label)) {
          unit = details.flow_unit || "lpm";
        } else if (/power|motor/i.test(rule.label)) {
          unit = details.power_unit || "HP";
        } else if (/fill.*time/i.test(rule.label)) {
          unit = details.fill_time_unit || null;
        }
      }
      rows.push({
        label: rule ? rule.label : prettifyKey(key),
        value: rule ? rule.format(value, unit) : formatDetailValue(value),
      });
    });
    return rows;
  }

  /** Renders the backend's real {flow, head} performance curve as an SVG line
   * chart, with the pump's actual matched duty point marked on the curve. */
  function buildPerformanceCurveSVG(curvePoints, matchedHead, flowAtMatch, headUnit) {
    var width = 300;
    var height = 190;
    var padding = 32;

    var points = curvePoints
      .filter(function (p) {
        return typeof p.flow === "number" && typeof p.head === "number";
      })
      .slice()
      .sort(function (a, b) {
        return a.flow - b.flow;
      });
    if (!points.length) return null;

    var maxFlow = Math.max.apply(
      null,
      points.map(function (p) {
        return p.flow;
      })
    );
    var maxHead = Math.max.apply(
      null,
      points.map(function (p) {
        return p.head;
      })
    );
    if (!maxFlow || !maxHead) return null;

    function xFor(flow) {
      return padding + (flow / maxFlow) * (width - padding * 2);
    }
    function yFor(head) {
      return height - padding - (head / maxHead) * (height - padding * 2);
    }

    var pathD = points
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + xFor(p.flow).toFixed(1) + "," + yFor(p.head).toFixed(1);
      })
      .join(" ");

    var markup =
      '<svg viewBox="0 0 ' +
      width +
      " " +
      height +
      '" width="100%" height="190" role="img" aria-label="Pump performance curve">' +
      '<line x1="' +
      padding +
      '" y1="' +
      padding / 2 +
      '" x2="' +
      padding +
      '" y2="' +
      (height - padding) +
      '" stroke="#e4e7e6" stroke-width="1" />' +
      '<line x1="' +
      padding +
      '" y1="' +
      (height - padding) +
      '" x2="' +
      (width - padding / 2) +
      '" y2="' +
      (height - padding) +
      '" stroke="#e4e7e6" stroke-width="1" />' +
      '<path d="' +
      pathD +
      '" fill="none" stroke="#3f8f7f" stroke-width="2.5" stroke-linejoin="round" />';

    if (typeof flowAtMatch === "number" && typeof matchedHead === "number") {
      var dotX = xFor(flowAtMatch);
      var dotY = yFor(matchedHead);
      markup += '<circle cx="' + dotX.toFixed(1) + '" cy="' + dotY.toFixed(1) + '" r="5" fill="#2f6f62" stroke="#fff" stroke-width="2" />';

      var unit = headUnit || "m";
      var tipLines = [formatDetailValue(flowAtMatch), formatDetailValue(matchedHead) + " " + unit];
      var tipW = 56;
      var tipH = 34;
      var tipX = Math.min(Math.max(dotX - tipW / 2, padding), width - padding / 2 - tipW);
      var tipY = Math.max(dotY - tipH - 10, 2);
      markup +=
        '<rect x="' +
        tipX.toFixed(1) +
        '" y="' +
        tipY.toFixed(1) +
        '" width="' +
        tipW +
        '" height="' +
        tipH +
        '" rx="6" fill="#fff" stroke="#e4e7e6" stroke-width="1" />' +
        '<text x="' +
        (tipX + tipW / 2).toFixed(1) +
        '" y="' +
        (tipY + 14).toFixed(1) +
        '" text-anchor="middle" font-size="10" font-weight="700" fill="#1c2a28">' +
        tipLines[0] +
        "</text>" +
        '<text x="' +
        (tipX + tipW / 2).toFixed(1) +
        '" y="' +
        (tipY + 26).toFixed(1) +
        '" text-anchor="middle" font-size="10" font-weight="700" fill="#1c2a28">' +
        tipLines[1] +
        "</text>";
    }

    markup +=
      '<text x="' +
      width / 2 +
      '" y="' +
      (height - 6) +
      '" text-anchor="middle" font-size="10" fill="#6b7a78">Flow</text>' +
      '<text x="10" y="' +
      height / 2 +
      '" text-anchor="middle" font-size="10" fill="#6b7a78" transform="rotate(-90 10 ' +
      height / 2 +
      ')">Head</text>' +
      "</svg>";

    return markup;
  }

  // A details field naming the pump's category (e.g. "End-Suction Centrifugal
  // Pump") is shown as a subtitle under the model name when the backend
  // provides one; nothing is fabricated when it doesn't.
  function findPumpSubtitle(details) {
    var key = Object.keys(details).find(function (k) {
      return /type|category|series/i.test(k);
    });
    return key ? details[key] : null;
  }

  var PD_TABS = ["Overview", "Features"];

  function openPumpDetailsModal(recommendation) {
    el.detailsBody.innerHTML = "";

    var details = recommendation.details || {};
    var subtitle = findPumpSubtitle(details);

    var modelRow = document.createElement("div");
    modelRow.className = "pd-model-row";
    var modelName = document.createElement("div");
    modelName.className = "pd-model-name";
    modelName.textContent = recommendation.model_name || "Unknown model";
    modelRow.appendChild(modelName);
    el.detailsBody.appendChild(modelRow);

    if (subtitle) {
      var subtitleEl = document.createElement("div");
      subtitleEl.className = "pd-subtitle";
      subtitleEl.textContent = subtitle;
      el.detailsBody.appendChild(subtitleEl);
    }

    var tabs = document.createElement("div");
    tabs.className = "pd-tabs";
    var tabPanels = {};
    PD_TABS.forEach(function (label, i) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pd-tab" + (i === 0 ? " active" : "");
      btn.textContent = label;
      btn.disabled = false;
      tabs.appendChild(btn);
    });
    el.detailsBody.appendChild(tabs);

    var panelContainer = document.createElement("div");
    panelContainer.className = "pd-panel-container";

    var overviewPanel = document.createElement("div");
    overviewPanel.className = "pd-panel active";
    overviewPanel.setAttribute("data-tab", "Overview");

    var imageUrl = getPumpImagePath(recommendation.model_name);
    if (imageUrl) {
      var imgContainer = document.createElement("div");
      imgContainer.className = "pd-image-container";
      var img = document.createElement("img");
      img.src = imageUrl;
      img.alt = recommendation.model_name || "Pump image";
      img.className = "pd-image";
      img.style.display = "block";
      img.style.cursor = "pointer";
      img.onerror = function () {
        imgContainer.style.display = "none";
      };
      imgContainer.appendChild(img);
      overviewPanel.appendChild(imgContainer);
    }

    var headUnit = state.dynamicAnswers[unitFieldNameFor("head")] || null;
    var curveMarkup =
      details.performance_curve && details.performance_curve.length
        ? buildPerformanceCurveSVG(details.performance_curve, details.matched_head, details.flow, headUnit)
        : null;

    if (curveMarkup) {
      var panelTitle = document.createElement("div");
      panelTitle.className = "pd-panel-title";
      panelTitle.textContent = "Performance Curve";
      overviewPanel.appendChild(panelTitle);

      var chartWrap = document.createElement("div");
      chartWrap.style.padding = "12px 0";
      chartWrap.innerHTML = curveMarkup;
      overviewPanel.appendChild(chartWrap); 

      var legend = document.createElement("div");
      legend.className = "chart-legend";
      legend.innerHTML = '<span class="dot"></span> Your matched operating point';
      overviewPanel.appendChild(legend);
    }

    var techTitle = document.createElement("div");
    techTitle.className = "tech-points-title";
    techTitle.textContent = "Technical Data";
    overviewPanel.appendChild(techTitle);

    var table = document.createElement("div");
    table.className = "specs-table overview-specs";
    var iconMap = {
      "Article No.": "🏷️",
      "Target Head": "📍",
      "Head": "🏔️",
      "Flow": "💧",
      "Flow Rate": "💧",
      "Motor Power": "⚙️",
      "Phase": "⚡",
      "Fluid Temperature": "🌡️",
      "Connection": "🔌"
    };
    buildTechnicalPointsRows(recommendation).forEach(function (row) {
      var line = document.createElement("div");
      line.className = "spec-line overview-spec-line";
      var icon = iconMap[row.label] || "•";

      var iconBox = document.createElement("div");
      iconBox.className = "spec-icon-box";
      iconBox.textContent = icon;
      line.appendChild(iconBox);

      var k = document.createElement("span");
      k.textContent = row.label;
      var v = document.createElement("span");
      v.textContent = row.value;
      line.appendChild(k);
      line.appendChild(v);
      table.appendChild(line);
    });
    overviewPanel.appendChild(table);

    panelContainer.appendChild(overviewPanel);

    var featuresPanel = document.createElement("div");
    featuresPanel.className = "pd-panel";
    featuresPanel.setAttribute("data-tab", "Features");

    if (recommendation.features && recommendation.features.length > 0) {
      var featuresList = document.createElement("ul");
      featuresList.className = "features-list";
      recommendation.features.forEach(function (feature) {
        var li = document.createElement("li");
        li.className = "feature-item";
        li.textContent = feature;
        featuresList.appendChild(li);
      });
      featuresPanel.appendChild(featuresList);
    } else {
      var noFeatures = document.createElement("p");
      noFeatures.className = "no-features";
      noFeatures.textContent = "No features available for this pump.";
      featuresPanel.appendChild(noFeatures);
    }

    panelContainer.appendChild(featuresPanel);
    el.detailsBody.appendChild(panelContainer);

    var tabButtons = tabs.querySelectorAll(".pd-tab");
    var switchTab = function (index) {
      tabButtons.forEach(function (b) {
        b.classList.remove("active");
      });
      tabButtons[index].classList.add("active");

      var panels = panelContainer.querySelectorAll(".pd-panel");
      panels.forEach(function (panel) {
        panel.classList.remove("active");
      });
      var targetPanel = panelContainer.querySelector('[data-tab="' + PD_TABS[index] + '"]');
      if (targetPanel) {
        targetPanel.classList.add("active");
      }
    };

    tabButtons.forEach(function (btn, i) {
      btn.addEventListener("click", function () {
        switchTab(i);
      });
    });

    // Swipe gesture support for tabs
    var touchStartX = 0;
    var touchEndX = 0;
    var currentTabIndex = 0;

    el.detailsBackdrop.addEventListener("touchstart", function (e) {
      touchStartX = e.changedTouches[0].screenX;
    }, false);

    el.detailsBackdrop.addEventListener("touchend", function (e) {
      touchEndX = e.changedTouches[0].screenX;
      var swipeThreshold = 50;

      if (touchStartX - touchEndX > swipeThreshold) {
        // Swiped left - go to next tab (Features)
        currentTabIndex = Math.min(currentTabIndex + 1, PD_TABS.length - 1);
        switchTab(currentTabIndex);
      } else if (touchEndX - touchStartX > swipeThreshold) {
        // Swiped right - go to previous tab (Overview)
        currentTabIndex = Math.max(currentTabIndex - 1, 0);
        switchTab(currentTabIndex);
      }
    }, false);

    el.detailsBackdrop.hidden = false;
  }

  function closePumpDetailsModal() {
    el.detailsBackdrop.hidden = true;
  }

  function buildRecommendationCard(recommendation, tierLabel) {
    var card = document.createElement("div");
    card.className = "card";

    var details = recommendation.details || {};

    var banner = document.createElement("div");
    banner.className = "card-banner";
    banner.appendChild(document.createTextNode(tierLabel));

    var body = document.createElement("div");
    body.className = "card-body";

    var catLabel = document.createElement("div");
    catLabel.className = "cat-label";
    catLabel.textContent = "Model";

    var modelName = document.createElement("div");
    modelName.className = "model-name";
    modelName.textContent = recommendation.model_name || "Unknown model";

    var specs = document.createElement("div");
    specs.className = "specs";

    var icon = document.createElement("div");
    icon.className = "pump-icon";

    var imageUrl = getPumpImagePath(recommendation.model_name);
    if (imageUrl) {
      var img = document.createElement("img");
      img.src = imageUrl;
      img.alt = recommendation.model_name || "Pump image";
      img.className = "pump-icon-image";
      icon.appendChild(img);
    } else {
      icon.innerHTML = PUMP_ICON_SVG;
    }

    var table = document.createElement("div");
    table.className = "specs-table";

    // Display new nested specs format (heat_circulation, domestic_hot_water) in simple style
    if (details.specs && typeof details.specs === "object") {
      var specLabels = {
        "flow": "Flow",
        "head": "Head",
        "fluid_temp": "Fluid Temperature",
        "connection": "Connection"
      };
      Object.keys(details.specs).forEach(function (key) {
        if (details.specs[key]) {
          var line = document.createElement("div");
          line.className = "spec-line";
          var k = document.createElement("span");
          k.textContent = specLabels[key] || prettifyKey(key);
          var v = document.createElement("span");
          v.textContent = String(details.specs[key]);
          line.appendChild(k);
          line.appendChild(v);
          table.appendChild(line);
        }
      });
    }

    // Display old format specs (pressure_boosting, dewatering, etc)
    DETAIL_DISPLAY_RULES.forEach(function (rule) {
      var matchedKey = Object.keys(details).find(rule.test);
      if (matchedKey == null || details[matchedKey] == null || details[matchedKey] === "") return;
      var line = document.createElement("div");
      line.className = "spec-line";
      var k = document.createElement("span");
      k.textContent = rule.label;
      var v = document.createElement("span");
      var unit = null;
      if (/head/i.test(rule.label)) {
        unit = details.head_unit || state.dynamicAnswers[unitFieldNameFor("head")] || "m";
      } else if (/flow/i.test(rule.label)) {
        unit = details.flow_unit || "lpm";
      } else if (/power|motor/i.test(rule.label)) {
        unit = details.power_unit || "HP";
      } else if (/fill.*time/i.test(rule.label)) {
        unit = details.fill_time_unit || null;
      }
      v.textContent = rule.format(details[matchedKey], unit);
      line.appendChild(k);
      line.appendChild(v);
      table.appendChild(line);
    });
    if (recommendation.art_no != null) {
      var artLine = document.createElement("div");
      artLine.className = "spec-line";
      var artKey = document.createElement("span");
      artKey.textContent = "Article No.";
      var artVal = document.createElement("span");
      artVal.textContent = String(recommendation.art_no);
      artLine.appendChild(artKey);
      artLine.appendChild(artVal);
      table.appendChild(artLine);
    }

    specs.appendChild(icon);
    specs.appendChild(table);

    var viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.className = "view-btn";
    viewBtn.innerHTML = LIST_ICON_SVG + "View Pump Details";
    viewBtn.addEventListener("click", function () {
      openPumpDetailsModal(recommendation);
    });

    var selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "view-btn select-btn";
    var isSelected = state.selectedPump && state.selectedPump.recommendation.model_name === recommendation.model_name;
    selectBtn.textContent = isSelected ? "✓ Selected" : "Select";
    if (isSelected) selectBtn.classList.add("selected");

    var isSameUseCaseAfterPincode = state.pincodeSubmitted && state.pincodeSubmittedUseCase === state.useCaseSlug;
    if (isSameUseCaseAfterPincode && !isSelected) {
      selectBtn.disabled = true;
      selectBtn.title = "Email verification in progress for " + (state.selectedPump ? state.selectedPump.recommendation.model_name : "selected pump") + " in this application";
    }

    selectBtn.addEventListener("click", function () {
      var newPumpModel = recommendation.model_name || "pump";
      var currentPumpModel = state.selectedPump ? state.selectedPump.recommendation.model_name : null;
      var isDifferentUseCase = state.pincodeSubmittedUseCase && state.pincodeSubmittedUseCase !== state.useCaseSlug;

      console.log("[selectBtn click] ===== PUMP SELECTION START =====");
      console.log("[selectBtn click] newPumpModel:", newPumpModel);
      console.log("[selectBtn click] currentPumpModel:", currentPumpModel);
      console.log("[selectBtn click] state.pincodeSubmitted:", state.pincodeSubmitted);
      console.log("[selectBtn click] isDifferentUseCase:", isDifferentUseCase);
      console.log("[selectBtn click] isSameUseCaseAfterPincode:", isSameUseCaseAfterPincode);

      if (state.pincodeSubmitted && !isDifferentUseCase) {
        console.log("[selectBtn click] SCENARIO: Pincode submitted in same use case - blocking change");
        showPumpSelectionModal(
          newPumpModel,
          newPumpModel,
          function () {
            closePumpSelectionModal();
          },
          function () {
            closePumpSelectionModal();
          }
        );
        var messageEl = document.querySelector(".pump-modal-message");
        if (messageEl) {
          messageEl.textContent = "Email verification process already started for " + currentPumpModel + " in this application. To select a different pump, explore other applications or wait for the current process to complete.";
        }
        return;
      }

      if (state.selectedPump && currentPumpModel === newPumpModel) {
        console.log("[selectBtn click] SCENARIO: Same pump selected again - already selected");
        showPumpSelectionModal(
          newPumpModel,
          newPumpModel,
          function () {
            closePumpSelectionModal();
          },
          function () {
            closePumpSelectionModal();
          }
        );
        var messageEl = document.querySelector(".pump-modal-message");
        if (messageEl) {
          messageEl.textContent = "You've already selected " + newPumpModel + ". Please proceed with email verification or select a different pump.";
        }
        return;
      }

      var confirmSelection = function () {
        state.selectedPump = { recommendation: recommendation, tierLabel: tierLabel };

        // Remove any previous pump selection messages
        state.messages = state.messages.filter(function(msg) {
          return !(msg.kind === "html" && msg.html && msg.html.indexOf("Great! You've selected") !== -1);
        });

        var pumpModel = recommendation.model_name || "pump";
        var html = "Great! You've selected <span style='color: #009C82; font-weight: bold;'>" + pumpModel + "</span>. To get the selection in your mailbox, please provide your email ID.";
        addBotHtmlMessage(html);
        console.log('[selectBtn click] Selected pump:', pumpModel, 'for use case:', state.useCaseSlug);
        jumpToStep("lead-email");
        render();
      };

      if (state.selectedPump && currentPumpModel && currentPumpModel !== newPumpModel && !isDifferentUseCase) {
        console.log("[selectBtn click] SCENARIO: Switching pumps in same use case - show confirmation modal");
        showPumpSelectionModal(currentPumpModel, newPumpModel, confirmSelection, function () {
          closePumpSelectionModal();
        });
      } else if (isDifferentUseCase && state.selectedPump && currentPumpModel && currentPumpModel !== newPumpModel) {
        console.log("[selectBtn click] SCENARIO: Selecting pump for different use case - no modal, direct selection");
        confirmSelection();
      } else {
        console.log("[selectBtn click] SCENARIO: No prior selection or first pump in this use case");
        confirmSelection();
      }
    });

    body.appendChild(catLabel);
    body.appendChild(modelName);
    body.appendChild(specs);
    body.appendChild(viewBtn);
    body.appendChild(selectBtn);

    card.appendChild(banner);
    card.appendChild(body);
    return card;
  }

  function buildRecommendationRow(message) {
    var row = document.createElement("div");
    row.className = "row bot";
    row.style.maxWidth = "100%";
    row.style.gap = "10px";
    row.appendChild(buildRecommendationCard(message.recommendation, "Standard Fit"));

    var alternatives = message.tiedAlternatives || [];
    if (alternatives.length) {
      var alternativeLabel = (state.useCaseSlug === "heat_circulation" || state.useCaseSlug === "domestic_hot_water")
        ? "Premium Fit"
        : "Alternative";
      alternatives.forEach(function (alt) {
        if (alt && typeof alt === "object" && alt.model_name) {
          row.appendChild(buildRecommendationCard(alt, alternativeLabel));
        }
      });
    }
    return row;
  }

  function buildOptionCard(option, onClick, index) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "option-card";

    // Check if it's a simple list option (has index and no icon image)
    var isSimpleList = index !== undefined && index !== null &&
                       (!option.icon || !/\.(png|jpg|jpeg|gif|svg)$/i.test(option.icon));

    if (isSimpleList) {
      // Simple numbered text style design
      var number = document.createElement("span");
      number.className = "option-number-text";
      number.textContent = String(index + 1);

      var label = document.createElement("span");
      label.className = "option-text-label";
      label.textContent = option.label;

      card.appendChild(number);
      card.appendChild(label);
    } else {
      // Original card design for application options
      var icon = document.createElement("span");
      icon.className = "option-icon";

      if (option.icon && /\.(png|jpg|jpeg|gif|svg)$/i.test(option.icon)) {
        var img = document.createElement("img");
        img.src = option.icon;
        img.alt = option.label;
        img.className = "option-image";
        icon.appendChild(img);
      } else {
        icon.textContent = option.icon || "•";
      }

      var text = document.createElement("span");
      text.className = "option-text";

      var title = document.createElement("span");
      title.className = "option-title";
      title.textContent = option.label;
      text.appendChild(title);

      if (option.description || option.subtitle) {
        var subtitle = document.createElement("span");
        subtitle.className = "option-subtitle";
        subtitle.textContent = option.description || option.subtitle;
        text.appendChild(subtitle);
      }

      card.appendChild(icon);
      card.appendChild(text);
    }

    card.addEventListener("click", onClick);
    return card;
  }

  function buildMessageRow(message) {
    var row = document.createElement("div");
    row.className = "row " + message.role;

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    if (message.kind === "html") {
      bubble.innerHTML = message.html;
    } else {
      var parsedHTML = message.text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      bubble.innerHTML = parsedHTML;
    }

    row.appendChild(bubble);
    return row;
  }

  function composerPlaceholder() {
    if (state.awaitingKind === "dynamic-input" && state.currentQuestion) {
      var q = state.currentQuestion;
      var hint = q.unit ? " in " + q.unit : "";
      return "Enter a value" + hint + (q.optional ? ", or 'skip'" : "");
    }
    if (state.awaitingKind === "input") return getStep(state.currentStepId).placeholder;
    if (state.awaitingKind === "loading") return "Checking...";
    return "Choose an option above";

  }

  function render() {
    el.thread.innerHTML = "";
    state.messages.forEach(function (message) {
      if (message.kind === "welcome") {
        el.thread.appendChild(buildWelcomeCard());
        return;
      }
      if (message.kind === "recommendation") {
        el.thread.appendChild(buildRecommendationRow(message));
        return;
      }
      el.thread.appendChild(buildMessageRow(message));
    });

    if (state.virtualOptions) {
      var vOptions = document.createElement("div");
      vOptions.className = "option-list";
      if (state.currentQuestion && CATEGORY_QUESTION_KEYS.includes(state.currentQuestion.key)) {
        vOptions.classList.add("categorical");
        if (state.useCaseSlug === "heat_circulation") {
          vOptions.classList.add("heat-circuits-style");
        }
      }
      state.virtualOptions.forEach(function (option, index) {
        vOptions.appendChild(
          buildOptionCard(option, function () {
            state.virtualOptions = null;
            option.onSelect();
          }, index)
        );
      });
      el.thread.appendChild(vOptions);
    } else if (state.awaitingKind === "options") {
      var step = getStep(state.currentStepId);
      var optionsArray = typeof step.options === 'function' ? step.options(state.answers) : step.options;
      var options = document.createElement("div");
      options.className = "option-list";
      if (state.currentQuestion && CATEGORY_QUESTION_KEYS.includes(state.currentQuestion.key)) {
        options.classList.add("categorical");
        if (state.useCaseSlug === "heat_circulation") {
          options.classList.add("heat-circuits-style");
        }
      }
      optionsArray.forEach(function (option, index) {
        options.appendChild(
          buildOptionCard(option, function () {
            submitOption(option.value, option.label);
          }, index)
        );
      });
      el.thread.appendChild(options);
    }

    var isInputStep =
      ((state.awaitingKind === "input" || state.awaitingKind === "dynamic-input" || state.awaitingKind === "text") &&
      !state.virtualOptions) || !!state.confirmationHandler;
    el.composerInput.disabled = !isInputStep;
    el.composerInput.placeholder = composerPlaceholder();
    if (!isInputStep) el.composerInput.value = "";
    el.sendBtn.disabled = !isInputStep || !el.composerInput.value.trim();
    if (isInputStep) {
      el.composerInput.focus();
    }

    if (state.inputError) {
      el.inputError.textContent = state.inputError;
      el.inputError.hidden = false;
    } else {
      el.inputError.hidden = true;
    }

    // Scroll to latest message - but not for application list or pump recommendations
    var lastMessage = state.messages[state.messages.length - 1];
    var hasRecommendation = lastMessage && lastMessage.recommendation;
    var isApplicationStep = state.currentStepId === "application";
    var isDynamicQuestion = state.awaitingKind === "dynamic-input" || state.awaitingKind === "input" ||
                            state.awaitingKind === "text";

    setTimeout(function () {
      if (!hasRecommendation && !isApplicationStep && isDynamicQuestion) {
        // Only scroll for dynamic questions - to show the current question
        var lastOptionList = el.thread.querySelector('.option-list:last-of-type');
        if (lastOptionList) {
          lastOptionList.scrollIntoView({ behavior: 'smooth', block: 'end' });
        } else {
          // Scroll to show the latest message/question
          el.thread.scrollTop = el.thread.scrollHeight;
        }
      }
      // Don't scroll for:
      // - Application cards (isApplicationStep)
      // - Pump recommendations (hasRecommendation)
    }, 150);
  }

  function handleSend() {
    if (el.composerInput.disabled) return;
    var value = el.composerInput.value;
    if (!value.trim()) return;

    // Prevent submission while loading
    if (state.awaitingKind === "loading") {
      console.log("[handleSend] Already loading, ignoring submission");
      return;
    }

    el.composerInput.value = "";
    if (state.confirmationHandler) {
      state.confirmationHandler(value);
    } else if (state.awaitingKind === "dynamic-input") {
      submitDynamicAnswer(value);
    } else {
      submitText(value);
    }
  }

  function showRefreshConfirmation() {
    el.confirmationModal.hidden = false;
  }

  function closeRefreshConfirmation() {
    el.confirmationModal.hidden = true;
  }

  function showPumpSelectionModal(currentPump, newPump, onConfirm, onCancel) {
    if (!el.pumpSelectionModal) {
      el.pumpSelectionModal = document.getElementById("pump-selection-modal");
    }
    if (!el.pumpSelectionModal) {
      console.error("Pump selection modal element not found");
      return;
    }

    var messageEl = el.pumpSelectionModal.querySelector(".pump-modal-message");
    var confirmBtn = el.pumpSelectionModal.querySelector(".pump-modal-confirm");
    var cancelBtn = el.pumpSelectionModal.querySelector(".pump-modal-cancel");

    if (currentPump) {
      messageEl.textContent = "Do you want to switch from " + currentPump + " to " + newPump + "?";
    } else {
      messageEl.textContent = "Confirm selection: " + newPump;
    }

    confirmBtn.onclick = function () {
      el.pumpSelectionModal.hidden = true;
      if (onConfirm) onConfirm();
    };

    cancelBtn.onclick = function () {
      el.pumpSelectionModal.hidden = true;
      if (onCancel) onCancel();
    };

    el.pumpSelectionModal.hidden = false;
  }

  function closePumpSelectionModal() {
    if (el.pumpSelectionModal) {
      el.pumpSelectionModal.hidden = true;
    }
  }

  function refreshChat() {
    state.messages = [];
    state.selectedPump = null;
    state.lastRecommendation = null;
    state.dynamicAnswers = {};
    state.clarificationAttempts = {};
    state.clarificationUserInput = {};
    state.currentQuestion = null;
    state.awaitingKind = null;
    state.inputError = null;
    state.virtualOptions = null;
    state.useCaseSlug = null;
    state.currentStepId = null;
    state.pincodeSubmitted = false;
    state.pincodeSubmittedUseCase = null;
    initConversation();
    closeRefreshConfirmation();
    render();
  }

  document.addEventListener("DOMContentLoaded", function () {
    el.thread = document.getElementById("thread");
    el.composerInput = document.getElementById("composer-input");
    el.sendBtn = document.getElementById("send-btn");
    el.inputError = document.getElementById("input-error");
    el.detailsBackdrop = document.getElementById("details-backdrop");
    el.detailsBody = document.getElementById("details-body");
    el.detailsClose = document.getElementById("details-close");
    el.menuBtn = document.getElementById("menu-btn");
    el.confirmationModal = document.getElementById("confirmation-modal");
    el.confirmCancel = document.getElementById("confirm-cancel");
    el.confirmRefresh = document.getElementById("confirm-refresh");
    el.pumpSelectionModal = document.getElementById("pump-selection-modal");

    el.sendBtn.addEventListener("click", handleSend);
    el.composerInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") handleSend();
    });
    el.composerInput.addEventListener("input", function () {
      el.sendBtn.disabled = el.composerInput.disabled || !el.composerInput.value.trim();
    });

    el.detailsClose.addEventListener("click", closePumpDetailsModal);
    el.detailsBackdrop.addEventListener("click", function (event) {
      if (event.target === el.detailsBackdrop) closePumpDetailsModal();
    });

    if (el.pumpSelectionModal) {
      el.pumpSelectionModal.addEventListener("click", function (event) {
        if (event.target === el.pumpSelectionModal) closePumpSelectionModal();
      });
    }

    el.menuBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      showRefreshConfirmation();
    });
    el.confirmCancel.addEventListener("click", closeRefreshConfirmation);
    el.confirmRefresh.addEventListener("click", refreshChat);
    el.confirmationModal.addEventListener("click", function (event) {
      if (event.target === el.confirmationModal) closeRefreshConfirmation();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !el.detailsBackdrop.hidden) closePumpDetailsModal();
      if (event.key === "Escape" && !el.menuDropdown.hidden) closeMenu();
      if (event.key === "Escape" && !el.confirmationModal.hidden) closeRefreshConfirmation();
      if (event.key === "Escape" && el.pumpSelectionModal && !el.pumpSelectionModal.hidden) closePumpSelectionModal();
    });

    initConversation();
    render();
  });
})();
