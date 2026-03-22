import React from 'react';
import simulationGif from './simulation.gif';

export const HeroGraphic = () => {
    return (
        <div className="relative w-80 h-80 md:w-[420px] md:h-[420px] mx-auto group">
            {/* Animated Orbital Rings */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div
                    className="absolute w-[120%] h-[120%] border border-cyan-500/20 rounded-full"
                    style={{
                        animation: 'spin 20s linear infinite',
                    }}
                />
                <div
                    className="absolute w-[140%] h-[140%] border border-cyan-400/10 rounded-full"
                    style={{
                        animation: 'spin 30s linear infinite reverse',
                    }}
                />
                <div
                    className="absolute w-[160%] h-[160%] border border-cyan-300/5 rounded-full"
                    style={{
                        animation: 'spin 40s linear infinite',
                    }}
                />
            </div>

            {/* Outer Glow Layers */}
            <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/30 via-teal-500/20 to-emerald-500/30 blur-3xl rounded-full scale-125 opacity-60 group-hover:opacity-80 transition-opacity duration-700" />
            <div className="absolute inset-0 bg-cyan-400/20 blur-2xl rounded-full scale-110 animate-pulse" style={{ animationDuration: '3s' }} />

            {/* Floating Particles */}
            <div className="absolute inset-0 pointer-events-none">
                {[...Array(8)].map((_, i) => (
                    <div
                        key={i}
                        className="absolute w-1 h-1 bg-cyan-400 rounded-full opacity-60"
                        style={{
                            left: `${20 + Math.random() * 60}%`,
                            top: `${20 + Math.random() * 60}%`,
                            animation: `float ${3 + i * 0.5}s ease-in-out infinite`,
                            animationDelay: `${i * 0.3}s`,
                        }}
                    />
                ))}
            </div>

            {/* Main Sphere Container */}
            <div
                className="relative w-full h-full rounded-full overflow-hidden shadow-2xl transform-gpu transition-all duration-700 group-hover:scale-105"
                style={{
                    boxShadow: `
                        0 0 60px rgba(0, 200, 200, 0.3),
                        0 0 120px rgba(0, 180, 180, 0.15),
                        inset 0 0 60px rgba(0, 0, 0, 0.5)
                    `,
                }}
            >
                {/* Glass Border Effect */}
                <div className="absolute inset-0 rounded-full ring-2 ring-white/10 ring-inset pointer-events-none z-20" />

                {/* GIF Content */}
                <img
                    src={simulationGif}
                    alt="Simulation"
                    className="w-full h-full object-cover scale-110"
                    style={{
                        filter: 'contrast(1.15) saturate(1.2) brightness(0.95)',
                    }}
                />

                {/* Depth Gradient - 3D Sphere Effect */}
                <div
                    className="absolute inset-0 rounded-full pointer-events-none"
                    style={{
                        background: `
                            radial-gradient(
                                ellipse 80% 80% at 50% 50%,
                                transparent 30%,
                                rgba(0, 20, 30, 0.4) 60%,
                                rgba(0, 10, 20, 0.7) 80%,
                                rgba(0, 5, 10, 0.9) 100%
                            )
                        `,
                    }}
                />

                {/* Top-Left Light Reflection */}
                <div
                    className="absolute inset-0 rounded-full pointer-events-none opacity-70"
                    style={{
                        background: `
                            radial-gradient(
                                ellipse 50% 50% at 25% 25%,
                                rgba(255, 255, 255, 0.25) 0%,
                                rgba(255, 255, 255, 0.1) 30%,
                                transparent 60%
                            )
                        `,
                    }}
                />

                {/* Fresnel Rim Light - Cyan Glow */}
                <div
                    className="absolute inset-0 rounded-full pointer-events-none"
                    style={{
                        background: `
                            radial-gradient(
                                circle at 50% 50%,
                                transparent 65%,
                                rgba(0, 200, 200, 0.15) 80%,
                                rgba(0, 220, 220, 0.25) 90%,
                                rgba(0, 240, 240, 0.1) 100%
                            )
                        `,
                    }}
                />

                {/* Bottom Right Accent Light */}
                <div
                    className="absolute inset-0 rounded-full pointer-events-none opacity-50"
                    style={{
                        background: `
                            radial-gradient(
                                ellipse 40% 40% at 75% 75%,
                                rgba(16, 185, 129, 0.2) 0%,
                                transparent 60%
                            )
                        `,
                    }}
                />

                {/* Glossy Surface Shine */}
                <div
                    className="absolute inset-0 rounded-full pointer-events-none mix-blend-overlay opacity-40"
                    style={{
                        background: 'linear-gradient(135deg, rgba(255,255,255,0.3) 0%, transparent 50%, rgba(0,0,0,0.1) 100%)',
                    }}
                />

                {/* Subtle Color Overlay */}
                <div className="absolute inset-0 rounded-full bg-gradient-to-br from-cyan-500/5 via-transparent to-emerald-500/5 mix-blend-color-dodge pointer-events-none" />
            </div>

            {/* Bottom Reflection/Shadow */}
            <div
                className="absolute -bottom-8 left-1/2 -translate-x-1/2 w-3/4 h-8 rounded-full blur-xl opacity-30"
                style={{
                    background: 'radial-gradient(ellipse at center, rgba(0, 200, 200, 0.4) 0%, transparent 70%)',
                }}
            />

            {/* CSS Keyframes */}
            <style>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                @keyframes float {
                    0%, 100% { 
                        transform: translateY(0) translateX(0) scale(1);
                        opacity: 0.6;
                    }
                    50% { 
                        transform: translateY(-20px) translateX(10px) scale(1.2);
                        opacity: 1;
                    }
                }
            `}</style>
        </div>
    );
};