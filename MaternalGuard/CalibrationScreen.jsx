import React, { useState, useEffect } from 'react';
import './CalibrationScreen.css';

const CalibrationScreen = ({ onComplete }) => {
  const [phase, setPhase] = useState('idle'); // 'idle', 'calibrating', 'complete'
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let interval;
    if (phase === 'calibrating') {
      // 10 seconds total, update every 50ms for smooth progress bar
      const totalTime = 10000;
      const tick = 50;
      let elapsed = 0;

      interval = setInterval(() => {
        elapsed += tick;
        const currentProgress = Math.min((elapsed / totalTime) * 100, 100);
        setProgress(currentProgress);

        if (elapsed >= totalTime) {
          clearInterval(interval);
          setPhase('complete');
        }
      }, tick);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [phase]);

  const startCalibration = () => {
    setPhase('calibrating');
    setProgress(0);
  };

  const proceedToLive = () => {
    if (onComplete) {
      onComplete();
    } else {
      console.log('Proceed to live monitoring');
    }
  };

  return (
    <div className="calibration-container">
      <div className="calibration-card">
        
        {/* HEADER */}
        <div className="calibration-header">
          <h2>🌸 MaternalGuard</h2>
          <p className="subtitle">Personal Baseline Calibration</p>
        </div>

        {/* CONTENT AREA */}
        <div className="calibration-content">

          {/* IDLE STATE */}
          {phase === 'idle' && (
            <div className="state-idle fade-in">
              <div className="icon-wrapper">
                <span className="calm-icon">🧘‍♀️</span>
              </div>
              <p className="instruction">
                Please sit back, close your eyes, and relax for 5 minutes. 
                We are establishing your personal cardiovascular baseline to provide highly accurate wellness insights.
              </p>
              <button className="primary-btn demo-btn" onClick={startCalibration}>
                Start Demo Calibration
              </button>
            </div>
          )}

          {/* CALIBRATING STATE */}
          {phase === 'calibrating' && (
            <div className="state-calibrating fade-in">
              <div className="pulse-container">
                <div className="pulse-circle"></div>
                <div className="pulse-circle delay"></div>
                <div className="pulse-core"></div>
              </div>
              
              <h3 className="gathering-text">Gathering 300 heartbeats...</h3>
              
              <div className="progress-bar-container">
                <div 
                  className="progress-bar-fill" 
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
            </div>
          )}

          {/* COMPLETE STATE */}
          {phase === 'complete' && (
            <div className="state-complete fade-in">
              <div className="success-icon-wrapper">
                <span className="success-icon">✨</span>
              </div>
              <h3>Calibration Complete</h3>
              <p className="success-subtitle">Your personal baseline has been established.</p>
              
              <div className="metrics-grid">
                <div className="metric-box">
                  <span className="metric-label">Resting BPM</span>
                  <span className="metric-value">68</span>
                </div>
                <div className="metric-box">
                  <span className="metric-label">Resting PTT</span>
                  <span className="metric-value">160 <span className="unit">ms</span></span>
                </div>
              </div>

              <button className="primary-btn proceed-btn" onClick={proceedToLive}>
                Proceed to Live Monitoring
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default CalibrationScreen;
