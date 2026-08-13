/* GoPoint Landing Page - Interactive AI Demo Controller */

class GoPointDemoEngine {
  constructor(mapShowcase, elevationPreview) {
    this.mapShowcase = mapShowcase;
    this.elevationPreview = elevationPreview;
    this.currentRoute = null;
    this.presets = window.GoPointPresets || [];
  }

  init() {
    this.bindEvents();
    // Default load first preset
    if (this.presets.length > 0) {
      this.loadRoute(this.presets[0]);
    }
  }

  bindEvents() {
    const promptInput = document.getElementById('demo-prompt-input');
    const chipBtns = document.querySelectorAll('.preset-chips .chip');

    // Preset Chip Clicks
    chipBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const presetId = e.currentTarget.getAttribute('data-preset');
        chipBtns.forEach(c => c.classList.remove('active'));
        e.currentTarget.classList.add('active');

        const preset = this.presets.find(p => p.id === presetId);
        if (preset) {
          if (promptInput) promptInput.value = preset.promptText;
          this.loadRoute(preset);
        }
      });
    });

    // Prompt Bar Input (Enter Key)
    if (promptInput) {
      promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.parseAndSimulate(promptInput.value);
        }
      });
    }

    // GPX Download Button
    const gpxBtn = document.getElementById('demo-gpx-btn');
    if (gpxBtn) {
      gpxBtn.addEventListener('click', () => {
        if (this.currentRoute && window.GoPointGPXExporter) {
          window.GoPointGPXExporter.exportRoute(this.currentRoute);
          if (window.showToast) {
            window.showToast(`Downloaded GPX file for ${this.currentRoute.title}`);
          }
        }
      });
    }
  }

  parseAndSimulate(userInputText) {
    if (!userInputText.trim()) return;

    // Search for closest preset match or generate dynamic parameters
    const textLower = userInputText.toLowerCase();
    let matchedPreset = this.presets.find(p => 
      textLower.includes(p.activity) || 
      textLower.includes(p.id) ||
      (p.promptText && textLower.includes(p.promptText.toLowerCase().substring(0, 10)))
    );

    if (!matchedPreset) {
      // Create dynamically parsed route simulation
      const distMatch = userInputText.match(/(\d+)\s*km/i);
      const targetDist = distMatch ? parseInt(distMatch[1]) : 25;
      const isHilly = textLower.includes('hilly') || textLower.includes('elevation') || textLower.includes('mountain');
      
      matchedPreset = {
        id: "dynamic-custom-route",
        title: `AI Generated Loop: "${userInputText}"`,
        activity: textLower.includes('run') ? 'running' : 'cycling',
        activityLabel: textLower.includes('run') ? 'Trail Run' : 'Cycling',
        promptText: userInputText,
        distanceKm: targetDist,
        elevationGainM: isHilly ? Math.round(targetDist * 16) : Math.round(targetDist * 8),
        estTime: `${Math.floor(targetDist / 22)}h ${Math.round((targetDist % 22) * 2.5)}m`,
        maxGradient: isHilly ? "9.4%" : "4.2%",
        surfaceBreakdown: isHilly ? { paved: 50, gravel: 35, trail: 15 } : { paved: 85, gravel: 15, trail: 0 },
        startPoint: [59.9242, 10.7027],
        center: [59.9450, 10.6800],
        zoom: 12,
        coordinates: this.presets[0].coordinates, // smooth polygon fallback
        elevationData: [
          [0.0, 40, 0.5],
          [targetDist * 0.3, isHilly ? 280 : 120, 5.0],
          [targetDist * 0.6, isHilly ? 420 : 160, 8.5],
          [targetDist * 0.85, 180, -3.2],
          [targetDist, 40, 0.0]
        ]
      };
    }

    this.loadRoute(matchedPreset);
    if (window.showToast) {
      window.showToast(`✨ Claude AI parsed prompt into structured parameters!`);
    }
  }

  loadRoute(routeData) {
    this.currentRoute = routeData;

    // Update Telemetry Panel Elements
    const titleEl = document.getElementById('demo-title');
    const badgeEl = document.getElementById('demo-activity-badge');
    const distEl = document.getElementById('demo-dist');
    const elevEl = document.getElementById('demo-elev');
    const timeEl = document.getElementById('demo-time');
    const gradEl = document.getElementById('demo-grad');

    if (titleEl) titleEl.textContent = routeData.title;
    if (badgeEl) badgeEl.textContent = routeData.activityLabel;
    if (distEl) distEl.textContent = `${routeData.distanceKm} km`;
    if (elevEl) elevEl.textContent = `+${routeData.elevationGainM} m`;
    if (timeEl) timeEl.textContent = routeData.estTime;
    if (gradEl) gradEl.textContent = routeData.maxGradient;

    // Surface Breakdown Bar
    const segPaved = document.querySelector('.surface-seg-paved');
    const segGravel = document.querySelector('.surface-seg-gravel');
    const segTrail = document.querySelector('.surface-seg-trail');
    const sb = routeData.surfaceBreakdown;

    if (segPaved) segPaved.style.width = `${sb.paved}%`;
    if (segGravel) segGravel.style.width = `${sb.gravel}%`;
    if (segTrail) segTrail.style.width = `${sb.trail}%`;

    // Render Map & Elevation Profile
    if (this.mapShowcase) {
      this.mapShowcase.renderRoute(routeData);
    }
    if (this.elevationPreview) {
      this.elevationPreview.render(routeData);
    }
  }
}

window.GoPointDemoEngine = GoPointDemoEngine;
