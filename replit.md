# VLG Discord Bot - Rust Community Management System

## Overview

VLG Helper is a comprehensive Discord bot designed for managing a large Russian Rust gaming community called "Деревня VLG" (Village VLG) with over 4,000 members. The bot serves as an automated community management system that handles member applications, role assignments, Steam profile verification, AI-powered assistance, and various administrative functions specific to Rust gaming communities.

The system is built around a hierarchical community structure with roles ranging from newcomers (Новичок) to citizens (Гражданин) and military roles (Ополчение), implementing a complex application workflow that validates Steam profiles, checks Rust gameplay hours, and ensures proper community integration.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Framework
- **Python 3.10+ with discord.py 2.5+** for Discord API integration
- **Asyncio-based architecture** for handling concurrent operations
- **Cog-based modular design** separating different functionalities
- **Web server component** (Flask) for health monitoring and status endpoints

### Application Processing System
The bot implements a sophisticated ticket-based application system where prospective members submit applications through Discord forms. The system automatically validates Steam profiles, checks Rust gameplay hours, verifies nickname formats, and processes applications through multiple approval stages with AI assistance for moderator decision-making.

### AI Integration Architecture
- **Multi-provider AI system** supporting both Groq and OpenRouter APIs
- **Knowledge Base (RAG) system** that indexes community rules and FAQ from specific Discord channels
- **Contextual response system** that provides community-specific answers using local knowledge
- **Automatic application analysis** helping moderators review member applications

### Steam API Integration
- **Comprehensive Steam profile validation** including account age, game ownership, and playtime verification
- **Automatic Steam ID resolution** from various URL formats (vanity URLs, direct profile links)
- **Caching system** for Steam API responses to reduce API calls and improve performance
- **Rust-specific validation** checking game ownership and minimum hour requirements

### Role Management System
- **Hierarchical role structure** with automatic progression paths from Newcomer to Citizen
- **Activity-based role assignments** using colored circles to indicate community participation levels
- **Military structure integration** for the community's militia system (Ополчение)
- **Automatic role validation** and cleanup functions

### Database and Caching
- **PostgreSQL integration** for persistent data storage of applications and user data
- **Multi-layer caching system** including in-memory caching for frequently accessed data
- **Fallback mechanisms** allowing operation when database is unavailable
- **Rate limiting and throttling** to prevent API abuse and ensure stability

### Security and Validation
- **Comprehensive nickname filtering** system blocking inappropriate content
- **Account age verification** ensuring minimum Discord account age requirements
- **Duplicate detection** preventing multiple applications from same users
- **Content moderation** with automatic flagging of problematic applications

### Administrative Interface
- **Admin panel system** for configuring bot settings through Discord interactions
- **Comprehensive logging system** with both console and Discord channel logging
- **Monitoring and health checks** with status endpoints and automatic error reporting
- **Moderation tools** for manual application review and community management

## External Dependencies

### Discord API Integration
- **discord.py library** for full Discord API functionality including slash commands, buttons, embeds, and role management
- **Application commands system** for user-friendly slash command interfaces

### AI and Language Processing
- **Groq API** as primary AI provider for natural language processing and application analysis
- **OpenRouter API** as secondary AI provider for redundancy and model diversity
- **Custom knowledge base system** for community-specific question answering

### Gaming Platform APIs
- **Steam Web API** for player profile verification, game library checking, and playtime validation
- **Steam Community API** for additional profile data and friend list verification

### Infrastructure Services
- **PostgreSQL database** (Supabase-hosted) for persistent data storage
- **aiohttp** for asynchronous HTTP requests to external APIs
- **Flask web server** for health monitoring and status endpoints

### Utility Libraries
- **asyncpg** for PostgreSQL database connections
- **asyncio** for concurrent operation handling
- **re (regex)** for text processing and validation
- **datetime** for time-based operations and scheduling
- **json** for configuration management and data serialization