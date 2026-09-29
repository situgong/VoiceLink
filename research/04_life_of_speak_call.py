# ============================================================================
# VoiceLink Research — Step 04: The Life of a Speak() Call
# ============================================================================
#
# PURPOSE: Trace exactly what happens from the moment an app calls Speak()
#          to when sound comes out of the speakers. This is our blueprint
#          for writing the COM DLL.
#
# READ THIS BEFORE WRITING ANY C++ CODE.
#
# ============================================================================

"""
╔══════════════════════════════════════════════════════════════════════════╗
║                                                                        ║
║              THE LIFE OF A SPEAK() CALL                                ║
║              A Complete Journey Through SAPI                           ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝

SCENARIO:
  A user opens Thorium Reader, selects "VoiceLink - Heart" as their voice,
  and clicks "Read Aloud" on a page that says:
    "Alice fell down the rabbit hole."

  What happens next? Let's trace EVERY step.


═══════════════════════════════════════════════════════════════════════════
 STEP 0: VOICE DISCOVERY (happens before Speak)
═══════════════════════════════════════════════════════════════════════════

When Thorium Reader opens its voice picker, it calls:

    SpEnumTokens(SPCAT_VOICES, ...)
    
This makes SAPI scan the registry at:
    HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\

Our installer already put entries there:

    HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\VoiceLink_af_heart\
        (Default)         = "VoiceLink - Heart"
        CLSID             = "{OUR-GUID-HERE}"        ← points to our DLL
        LangDataPath      = ""
        VoicePath         = ""
        
    HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\VoiceLink_af_heart\Attributes\
        Name              = "Heart"
        Gender            = "Female"
        Age               = "Adult"
        Language           = "409"                    ← 0x0409 = English US
        Vendor            = "VoiceLink"

    HKLM\SOFTWARE\Classes\CLSID\{OUR-GUID-HERE}\
        (Default)         = "VoiceLink TTS Engine"
    
    HKLM\SOFTWARE\Classes\CLSID\{OUR-GUID-HERE}\InprocServer32\
        (Default)         = "C:\\Program Files\\VoiceLink\\voicelink.dll"
        ThreadingModel    = "Both"

NOW the user sees "VoiceLink - Heart" in Thorium's voice dropdown.


═══════════════════════════════════════════════════════════════════════════
 STEP 1: USER SELECTS VOICE → COM CREATES OUR OBJECT
═══════════════════════════════════════════════════════════════════════════

When the user picks "VoiceLink - Heart":

1. Thorium tells SAPI: "Use this voice token"
   
2. SAPI reads the CLSID from the token → {OUR-GUID-HERE}

3. SAPI calls CoCreateInstance({OUR-GUID-HERE}, IID_ISpTTSEngine)

4. Windows COM runtime:
   a. Looks up CLSID in registry → finds InprocServer32 → path to our DLL
   b. Calls LoadLibrary("C:\\Program Files\\VoiceLink\\voicelink.dll")
   c. Calls our exported function: DllGetClassObject(CLSID, IID_IClassFactory)
   d. Our DLL returns an IClassFactory
   e. COM calls factory->CreateInstance(IID_ISpTTSEngine)
   f. Our factory creates a new VoiceLinkEngine object
   g. Returns ISpTTSEngine pointer to SAPI

5. SAPI calls engine->SetObjectToken(pToken)
   - Passes the voice token so we know WHICH voice was selected
   - We read the token's attributes to find voice ID = "af_heart"
   - We store this for later use in Speak()

CRITICAL UNDERSTANDING:
  Our DLL is loaded INTO Thorium's process. We're running inside Thorium.
  If we crash, Thorium crashes. If we leak memory, Thorium leaks memory.
  This is why C++ is the right choice — we need to be a well-behaved guest.


═══════════════════════════════════════════════════════════════════════════
 STEP 2: APP CALLS SPEAK → SAPI CALLS OUR ENGINE
═══════════════════════════════════════════════════════════════════════════

Thorium calls:
    pVoice->Speak(L"Alice fell down the rabbit hole.", SPF_DEFAULT, NULL)

SAPI processes this and calls our engine:

    HRESULT Speak(
        DWORD dwSpeakFlags,              // SPF_DEFAULT, SPF_ASYNC, etc.
        REFGUID rguidFormatId,            // Requested audio format GUID
        const WAVEFORMATEX* pWaveFormatEx,// Detailed format info
        const SPVTEXTFRAG* pTextFragList, // The text to speak (linked list!)
        ISpTTSEngineSite* pOutputSite     // Where to write audio + events
    );

Let's understand each parameter:

── dwSpeakFlags ──
  Bit flags. Usually SPF_DEFAULT (0). Can include:
  - SPF_ASYNC: Don't block (SAPI handles this, not us)
  - SPF_IS_XML: Text contains SSML markup
  - SPF_PURGEBEFORESPEAK: Cancel previous speech first

── rguidFormatId + pWaveFormatEx ──
  SAPI tells us what audio format it wants. It already negotiated this
  by calling our GetOutputFormat() earlier. For us:
  
    GUID = SPDFID_WaveFormatEx
    Format = 24000 Hz, 16-bit, mono PCM
    
  This is literally the same format Kokoro outputs! No conversion needed.

── pTextFragList (THE IMPORTANT ONE) ──
  This is NOT a simple string. It's a LINKED LIST of SPVTEXTFRAG structs:

    struct SPVTEXTFRAG {
        SPVTEXTFRAG* pNext;       // Next fragment in linked list
        SPVSTATE State;            // Voice state (rate, pitch, volume, etc.)
        LPCWSTR pTextStart;        // Pointer to start of text
        ULONG ulTextLen;           // Length of text
        ULONG ulTextSrcOffset;     // Offset in original text (for bookmarks)
    };

    struct SPVSTATE {
        SPVACTIONS eAction;        // SPVA_Speak, SPVA_Silence, SPVA_Bookmark...
        LONG RateAdj;              // Rate adjustment (-10 to +10)
        ULONG Volume;              // Volume (0-100)
        SPVPITCH PitchAdj;         // Pitch adjustment
        ULONG SilenceMSecs;        // Silence duration (if eAction=SPVA_Silence)
        ...
    };

  For simple text like "Alice fell down the rabbit hole", there's typically
  ONE fragment with eAction = SPVA_Speak.

  For SSML with rate/pitch changes, there are MULTIPLE fragments:
    Fragment 1: "Alice " (rate=0, volume=100)
    Fragment 2: "fell down" (rate=+2, volume=80)   ← rate changed via SSML
    Fragment 3: " the rabbit hole." (rate=0, volume=100)

  For VoiceLink v1, we'll concatenate all SPVA_Speak fragments into one
  text string and ignore rate/pitch adjustments. Later we can map them
  to Kokoro's speed parameter.

── pOutputSite ──
  This is our lifeline back to SAPI. It provides:
  
  pOutputSite->Write(pBuf, cb)    // Send audio data (PCM bytes)
  pOutputSite->GetActions()        // Check: should we stop/skip?
  pOutputSite->AddEvents(...)      // Fire events (sentence boundary, etc.)
  pOutputSite->GetRate(...)        // Get app-requested speaking rate
  pOutputSite->GetVolume(...)      // Get app-requested volume
  
  The Write() function is how we deliver audio. We call it repeatedly
  with chunks of PCM data. SAPI buffers and plays them.


═══════════════════════════════════════════════════════════════════════════
 STEP 3: OUR ENGINE TALKS TO THE PYTHON SERVER
═══════════════════════════════════════════════════════════════════════════

Inside our Speak() implementation:

    HRESULT VoiceLinkEngine::Speak(...) {
        // 1. Extract text from fragment list
        std::wstring fullText;
        for (auto* frag = pTextFragList; frag; frag = frag->pNext) {
            if (frag->State.eAction == SPVA_Speak) {
                fullText.append(frag->pTextStart, frag->ulTextLen);
            }
        }
        
        // 2. Convert wide string (UTF-16) to UTF-8 for HTTP
        std::string utf8Text = WideToUtf8(fullText);
        
        // 3. Build HTTP request
        //    POST http://127.0.0.1:7860/v1/tts
        //    {"text": "Alice fell down the rabbit hole.", "voice": "af_heart"}
        
        // 4. Send request, read streaming response
        //    The response is chunked PCM audio
        
        // 5. For each chunk received:
        //    a. Check if SAPI wants us to stop
        //       DWORD actions = pOutputSite->GetActions();
        //       if (actions & SPVES_ABORT) return S_OK;  // Cancel!
        //    b. Write PCM to SAPI
        //       pOutputSite->Write(chunkData, chunkSize);
        
        return S_OK;
    }

HTTP CLIENT INSIDE A DLL:
  We need to make HTTP requests from C++. Options:
  
  a. WinHTTP (Windows built-in) ← OUR CHOICE
     - Part of Windows, no extra dependencies
     - Supports chunked transfer encoding (streaming!)
     - Async API available
     - Used by NaturalVoiceSAPIAdapter
     
  b. libcurl
     - Cross-platform but needs to be bundled
     - Overkill for localhost-only communication
     
  c. cpp-httplib (header-only)
     - Simple, but doesn't support chunked reading well
  
  WinHTTP is perfect: zero dependencies, streaming support, proven.


═══════════════════════════════════════════════════════════════════════════
 STEP 4: AUDIO FLOWS BACK TO THE USER
═══════════════════════════════════════════════════════════════════════════

The timeline from the user's perspective:

  t=0ms     User clicks "Read Aloud"
  t=1ms     SAPI calls our Speak()
  t=2ms     We send HTTP POST to localhost:7860
  t=3ms     Python server receives request, starts Kokoro inference
  t=100ms   Kokoro generates first audio chunk (~1 sentence)
  t=102ms   HTTP chunked response sends first chunk
  t=103ms   Our DLL receives chunk, calls pOutputSite->Write()
  t=105ms   SAPI receives PCM, sends to audio driver
  t=110ms   USER HEARS FIRST AUDIO ← ~110ms total latency!
  
  t=150ms   Second chunk arrives, Write() again
  t=200ms   Third chunk arrives, Write() again
  ...
  t=800ms   Last chunk. Speak() returns S_OK.
  
  Total: User hears audio starting at ~110ms. That's faster than
  Azure cloud TTS (~500-2000ms) and feels essentially instant.


═══════════════════════════════════════════════════════════════════════════
 STEP 5: CANCELLATION  
═══════════════════════════════════════════════════════════════════════════

What if the user clicks STOP while we're speaking?

  1. Thorium calls pVoice->Speak("", SPF_PURGEBEFORESPEAK)
     (Or the equivalent cancel API)
     
  2. SAPI sets a flag on pOutputSite
  
  3. In our Speak() loop, we periodically check:
     DWORD actions = pOutputSite->GetActions();
     if (actions & SPVES_ABORT) {
         // Stop reading from HTTP stream
         // Close the connection
         // Return S_OK immediately
     }
  
  4. Our Speak() returns, SAPI is happy.

  This is why we check GetActions() BETWEEN chunks, not just once.
  If we don't check, the user clicks Stop but audio keeps playing
  until the model finishes generating. Bad UX.


═══════════════════════════════════════════════════════════════════════════
 STEP 6: CLEANUP  
═══════════════════════════════════════════════════════════════════════════

When Thorium closes:
  1. SAPI releases our engine: engine->Release()
  2. Our ref count drops to 0, destructor runs
  3. Eventually: COM calls DllCanUnloadNow()
  4. If ref count = 0, COM calls FreeLibrary() on our DLL
  5. Our DLL is unloaded from memory. Clean exit.

If we leak memory or COM references, the DLL never unloads.
Windows won't crash, but memory grows over time. 
This is why reference counting must be EXACT.


╔══════════════════════════════════════════════════════════════════════════╗
║                                                                        ║
║              WHAT WE MUST IMPLEMENT (THE CHECKLIST)                    ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝

Our DLL needs to export 4 functions and implement 4 COM interfaces.

═══════════════════════════════════════════════════════════════════════════
 DLL EXPORTS (4 functions)
═══════════════════════════════════════════════════════════════════════════

1. DllGetClassObject(CLSID, IID, ppv)
   - COM calls this to get our factory
   - We check if CLSID matches ours, create and return ClassFactory
   - This is the ENTRY POINT — the first function COM ever calls on us

2. DllCanUnloadNow()
   - COM calls this periodically: "Can I unload your DLL?"
   - We return S_OK if no objects alive, S_FALSE otherwise
   - Based on a global reference counter

3. DllRegisterServer()
   - Called by regsvr32.exe to register our voice
   - Creates ALL the registry entries shown in Step 0
   - This is what makes our voice appear in the voice list

4. DllUnregisterServer()
   - Called by regsvr32.exe /u to unregister
   - Removes all registry entries. Clean uninstall.


═══════════════════════════════════════════════════════════════════════════
 COM INTERFACES (4 interfaces, ~12 methods total)
═══════════════════════════════════════════════════════════════════════════

Interface 1: IUnknown (inherited by everything)
  ├── QueryInterface(riid, ppv)     // "Do you support this interface?"
  ├── AddRef()                       // Increment reference count
  └── Release()                      // Decrement; destroy if 0

Interface 2: IClassFactory  
  ├── CreateInstance(pOuter, riid, ppv)  // Create a new engine object
  └── LockServer(fLock)                   // Keep DLL loaded

Interface 3: ISpTTSEngine (the main one!)
  ├── Speak(flags, format, waveformat, textfrags, outputsite)
  └── GetOutputFormat(targetFmtId, targetWaveFormatEx, 
                      outputFmtId, ppCoMemOutputWaveFormatEx)

Interface 4: ISpObjectWithToken
  ├── SetObjectToken(pToken)     // SAPI tells us which voice was picked
  └── GetObjectToken(ppToken)    // SAPI asks which voice we're using


═══════════════════════════════════════════════════════════════════════════
 THE C++ CLASS HIERARCHY
═══════════════════════════════════════════════════════════════════════════

  // Our main engine class inherits from both SAPI interfaces
  class VoiceLinkEngine : public ISpTTSEngine, public ISpObjectWithToken {
  private:
      LONG m_refCount;           // Reference count (for AddRef/Release)
      ISpObjectToken* m_pToken;  // The voice token SAPI gave us
      std::string m_voiceId;     // e.g. "af_heart" (extracted from token)
      
  public:
      // IUnknown
      HRESULT QueryInterface(REFIID riid, void** ppv);
      ULONG AddRef();
      ULONG Release();
      
      // ISpTTSEngine
      HRESULT Speak(DWORD dwSpeakFlags, REFGUID rguidFormatId,
                    const WAVEFORMATEX* pWaveFormatEx,
                    const SPVTEXTFRAG* pTextFragList,
                    ISpTTSEngineSite* pOutputSite);
      HRESULT GetOutputFormat(const GUID* pTargetFmtId,
                              const WAVEFORMATEX* pTargetWaveFormatEx,
                              GUID* pOutputFormatId,
                              WAVEFORMATEX** ppCoMemOutputWaveFormatEx);
      
      // ISpObjectWithToken
      HRESULT SetObjectToken(ISpObjectToken* pToken);
      HRESULT GetObjectToken(ISpObjectToken** ppToken);
  };

  // Factory class — creates VoiceLinkEngine instances
  class VoiceLinkClassFactory : public IClassFactory {
      HRESULT QueryInterface(REFIID riid, void** ppv);
      ULONG AddRef();
      ULONG Release();
      HRESULT CreateInstance(IUnknown* pOuter, REFIID riid, void** ppv);
      HRESULT LockServer(BOOL fLock);
  };


═══════════════════════════════════════════════════════════════════════════
 MEMORY LAYOUT — WHAT COM ACTUALLY DOES IN RAM
═══════════════════════════════════════════════════════════════════════════

When SAPI has a pointer to our engine, here's what's in memory:

  pEngine points here:
  ┌──────────────────────────────────────┐
  │  vtable pointer (ISpTTSEngine)       │──→ [QueryInterface, AddRef, Release,
  │                                      │     Speak, GetOutputFormat]
  ├──────────────────────────────────────┤
  │  vtable pointer (ISpObjectWithToken) │──→ [QueryInterface, AddRef, Release,
  │                                      │     SetObjectToken, GetObjectToken]
  ├──────────────────────────────────────┤
  │  m_refCount = 1                      │
  │  m_pToken = 0x7ff...                 │
  │  m_voiceId = "af_heart"              │
  └──────────────────────────────────────┘

  COM uses VTABLE-BASED dispatch. This is why COM works across languages:
  any language that can follow function pointers can call COM methods.
  C++, Rust, C#, Python — they all just follow the same vtable layout.

  MULTIPLE INHERITANCE DETAIL:
  Our class inherits from TWO interfaces (ISpTTSEngine + ISpObjectWithToken).
  In C++, this gives us TWO vtable pointers at the top of the object.
  QueryInterface must handle this:
  
    if (riid == IID_ISpTTSEngine)
        *ppv = static_cast<ISpTTSEngine*>(this);    // First vtable
    else if (riid == IID_ISpObjectWithToken)
        *ppv = static_cast<ISpObjectWithToken*>(this);  // Second vtable
    
  The static_cast adjusts the pointer to point to the correct vtable.
  This is a CLASSIC COM pitfall.


═══════════════════════════════════════════════════════════════════════════
 GetOutputFormat — THE AUDIO FORMAT NEGOTIATION
═══════════════════════════════════════════════════════════════════════════

Before Speak(), SAPI calls GetOutputFormat() to ask:
  "What audio format can you produce?"

We respond: "24kHz, 16-bit, mono PCM" — always.

    HRESULT VoiceLinkEngine::GetOutputFormat(
        const GUID* pTargetFmtId,
        const WAVEFORMATEX* pTargetWaveFormatEx,
        GUID* pOutputFormatId,
        WAVEFORMATEX** ppCoMemOutputWaveFormatEx
    ) {
        // We always output 24kHz 16-bit mono
        *pOutputFormatId = SPDFID_WaveFormatEx;
        
        // Allocate WAVEFORMATEX using CoTaskMemAlloc (COM requirement!)
        WAVEFORMATEX* pFmt = (WAVEFORMATEX*)CoTaskMemAlloc(sizeof(WAVEFORMATEX));
        pFmt->wFormatTag = WAVE_FORMAT_PCM;
        pFmt->nChannels = 1;
        pFmt->nSamplesPerSec = 24000;
        pFmt->wBitsPerSample = 16;
        pFmt->nBlockAlign = 2;        // channels × (bitsPerSample / 8)
        pFmt->nAvgBytesPerSec = 48000; // sampleRate × blockAlign
        pFmt->cbSize = 0;
        
        *ppCoMemOutputWaveFormatEx = pFmt;
        return S_OK;
    }

WHY CoTaskMemAlloc?
  COM has a rule: if you allocate memory for the caller to free,
  you MUST use CoTaskMemAlloc. The caller frees with CoTaskMemFree.
  This is because caller and callee might use different heaps
  (different CRT versions, different DLLs). CoTaskMemAlloc uses 
  the COM allocator which both sides agree on.


═══════════════════════════════════════════════════════════════════════════
 THREADING — THE INVISIBLE COMPLEXITY
═══════════════════════════════════════════════════════════════════════════

Our registry says: ThreadingModel = "Both"

What does this mean?

  COM has "apartments" — threading models:
  - STA (Single-Threaded Apartment): One thread, no concurrency worries
  - MTA (Multi-Threaded Apartment): Multiple threads, you handle sync
  - "Both": Works in either apartment

  We say "Both" because:
  1. Some apps (Thorium/Electron) use MTA
  2. Some apps (old WinForms apps) use STA
  3. We want to work everywhere
  
  Our Speak() might be called from different threads.
  But in practice, SAPI serializes calls — it won't call Speak()
  on two threads simultaneously for the same engine instance.
  
  We still need thread-safe AddRef/Release (use InterlockedIncrement).


═══════════════════════════════════════════════════════════════════════════
 ERROR HANDLING — BEING A GOOD COM CITIZEN
═══════════════════════════════════════════════════════════════════════════

COM methods return HRESULT (a 32-bit error code). Rules:

  S_OK (0)          = Success
  S_FALSE (1)       = Success, but nothing happened
  E_NOINTERFACE     = QueryInterface: we don't support that interface
  E_OUTOFMEMORY     = Memory allocation failed
  E_FAIL            = Generic failure
  E_INVALIDARG      = Bad parameter
  SPERR_*           = SAPI-specific errors

NEVER throw C++ exceptions across COM boundaries!
  COM is language-neutral. The caller might be C#, Python, or Rust.
  They don't know how to catch C++ exceptions.
  
  Rule: catch ALL exceptions inside each COM method, return HRESULT.

    HRESULT Speak(...) {
        try {
            // ... our code ...
            return S_OK;
        } catch (const std::exception& e) {
            // Log error
            return E_FAIL;
        } catch (...) {
            return E_UNEXPECTED;
        }
    }


═══════════════════════════════════════════════════════════════════════════
 SERVER DOWN — GRACEFUL DEGRADATION
═══════════════════════════════════════════════════════════════════════════

What if our Python server isn't running when Speak() is called?

  1. WinHTTP connection to localhost:7860 fails immediately (~1ms)
  2. We return E_FAIL or SPERR_UNINITIALIZED
  3. SAPI tells the app "voice failed"
  4. Some apps fall back to another voice. Others show an error.

We could also:
  - Return silence (return S_OK with no Write calls) — app thinks we spoke
  - Return a short beep tone — user knows something's wrong
  - Cache a "server unavailable" audio clip and play that

For v1: return E_FAIL. Simple, correct, honest.


═══════════════════════════════════════════════════════════════════════════
 FILE STRUCTURE FOR THE COM DLL PROJECT
═══════════════════════════════════════════════════════════════════════════

  sapi_bridge/
  ├── CMakeLists.txt              // Build system (CMake)
  ├── src/
  │   ├── dllmain.cpp             // DLL entry point + 4 exports
  │   ├── class_factory.h/.cpp    // VoiceLinkClassFactory
  │   ├── tts_engine.h/.cpp       // VoiceLinkEngine (the big one)
  │   ├── http_client.h/.cpp      // WinHTTP wrapper for server communication
  │   ├── registry.h/.cpp         // Registry read/write helpers
  │   └── voicelink.def           // DLL export definitions
  ├── include/
  │   └── guids.h                 // Our CLSID and other GUIDs
  └── test/
      └── test_speak.ps1          // PowerShell test script


═══════════════════════════════════════════════════════════════════════════
 SUMMARY — THE WHOLE PICTURE
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────┐
  │ Thorium Reader (or any SAPI app)                                    │
  │                                                                     │
  │  pVoice->Speak("Alice fell down the rabbit hole.", SPF_DEFAULT, 0) │
  └────────────────────────────┬────────────────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ SAPI 5.4 (sapi.dll — Windows built-in)                             │
  │                                                                     │
  │  1. Parse text → SPVTEXTFRAG linked list                           │
  │  2. Call engine->GetOutputFormat() → 24kHz 16-bit mono             │
  │  3. Call engine->Speak(flags, format, frags, outputSite)           │
  └────────────────────────────┬────────────────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ voicelink.dll (OUR CODE — loaded in Thorium's process)             │
  │                                                                     │
  │  Speak() {                                                         │
  │    text = extract_text(pTextFragList)                               │
  │    response = WinHTTP_POST("localhost:7860/v1/tts", text, voice)   │
  │    while (chunk = response.read_chunk()) {                         │
  │      if (pOutputSite->GetActions() & SPVES_ABORT) break  // cancel │
  │      pOutputSite->Write(chunk.data, chunk.size)           // play! │
  │    }                                                               │
  │    return S_OK                                                     │
  │  }                                                                 │
  └────────────────────────────┬────────────────────────────────────────┘
                               │ HTTP (localhost)
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Python Server (separate process)                                    │
  │                                                                     │
  │  POST /v1/tts {"text": "...", "voice": "af_heart"}                 │
  │  → Kokoro pipeline → float32 audio → PCM int16 bytes              │
  │  → StreamingResponse (chunked transfer encoding)                   │
  └────────────────────────────┬────────────────────────────────────────┘
                               │
                               ▼
                          🔊 Speaker
"""

# That's the end of the educational document.
# No executable code here — this is pure documentation.
# 
# NEXT STEPS (once C++ tools are installed):
# 1. Create sapi_bridge/ directory structure
# 2. Write CMakeLists.txt
# 3. Implement dllmain.cpp (4 exports)
# 4. Implement class_factory (IClassFactory)
# 5. Implement tts_engine (ISpTTSEngine — the big one)
# 6. Implement http_client (WinHTTP wrapper)
# 7. Build → regsvr32 → test with PowerShell SAPI
# 8. Test with Thorium Reader!
