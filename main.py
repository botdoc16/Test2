from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import sqlite3
import uuid
import shutil
import os

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем все origins в тестовом режиме
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)

# Настраиваем пути для загрузки файлов
if 'VERCEL' in os.environ:
    UPLOAD_DIR = Path("/tmp/uploads")
    AVATARS_DIR = UPLOAD_DIR / "avatars"
else:
    UPLOAD_DIR = Path("uploads")
    AVATARS_DIR = UPLOAD_DIR / "avatars"

try:
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    # Монтируем статические файлы
    app.mount("/avatars", StaticFiles(directory=str(AVATARS_DIR)), name="avatars")
except Exception as e:
    print(f"Warning: Could not create upload directory: {str(e)}")

# --- DATABASE SETUP ---
try:
    # Для Vercel используем временную директорию
    if 'VERCEL' in os.environ:
        db_path = "/tmp/anime_data.db"
    else:
        db_path = "anime_data.db"
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
except Exception as e:
    print(f"Database connection error: {str(e)}")
    # Если не удалось подключиться к базе данных, создаем временное подключение в памяти
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cursor = conn.cursor()

def init_db():
    # Создаем таблицу users - основная информация о пользователях
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar_path TEXT,
            level INTEGER DEFAULT 1,
            exp INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Создаем таблицу achievements - достижения пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            icon_path TEXT,
            exp_reward INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Создаем таблицу user_achievements - связь пользователей с их достижениями
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            achievement_id INTEGER,
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (achievement_id) REFERENCES achievements(id),
            UNIQUE(user_id, achievement_id)
        )
    """)

    # Создаем таблицу roles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            user_id TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    # Создаем таблицу recent
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            anime_id TEXT,
            title TEXT,
            image_url TEXT,
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(user_id, anime_id)
        )
    """)

    # Создаем таблицу watch_progress
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            anime_id TEXT,
            title TEXT,
            image_url TEXT,
            status TEXT,
            episodes_watched INTEGER DEFAULT 0,
            total_episodes INTEGER DEFAULT 0,
            last_watch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    """)

    # Создаем таблицу favorites
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            anime_id TEXT,
            title TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    """)

    # Создаем таблицу administrators
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS administrators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            admin_level INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    # Создаем таблицу now_watching для "Сейчас смотрят" (глобально)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS now_watching (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_id TEXT,
            title TEXT,
            image_url TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(anime_id)
        )
    """)

    # Создаем таблицу reviews для отзывов пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Создаем таблицу для новостей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            author TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Проверяем наличие столбца created_at, если нет — добавляем
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'created_at' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        conn.commit()

    conn.commit()

init_db()

# --- MODELS ---
class Status(str, Enum):
    PLANNED = "planned"
    WATCHING = "watching"
    COMPLETED = "completed"
    DROPPED = "dropped"

class AnimeEntry(BaseModel):
    anime_id: str
    title: str
    image_url: Optional[str] = None

class UserCredentials(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class WatchProgress(BaseModel):
    user_id: str
    anime_id: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    status: Status
    episodes_watched: int = 0
    total_episodes: Optional[int] = None

class EpisodeProgress(BaseModel):
    user_id: str
    anime_id: str
    episode_number: int
    progress: float

class FavoriteAction(BaseModel):
    animeId: str
    action: Literal["add", "remove"]  # Более строгая валидация
    title: Optional[str] = None
    image_url: Optional[str] = None

class WatchStatusUpdate(BaseModel):
    animeId: str
    status: Status = Field(..., description="Status must be one of: planned, watching, completed, dropped")
    episodes: Optional[int] = 0
    title: Optional[str] = None
    image_url: Optional[str] = None

class UserUpdate(BaseModel):
    username: str
    email: Optional[str] = None

class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None

class AdminSetup(BaseModel):
    setupKey: str
    email: str

class AdminVerify(BaseModel):
    email: str
    setupKey: str

class UserRole(BaseModel):
    role: Literal["user", "admin"]

class RecentAnime(BaseModel):
    user_id: str
    anime_id: str
    title: str
    image_url: Optional[str] = None

class NowWatchingEntry(BaseModel):
    anime_id: str
    title: str
    image_url: Optional[str] = None

class Review(BaseModel):
    username: Optional[str] = None
    text: str
    created_at: Optional[str] = None

class News(BaseModel):
    id: Optional[int] = None
    title: str
    description: str
    author: Optional[str] = None
    created_at: Optional[str] = None

class Achievement(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
    icon_path: Optional[str] = None
    exp_reward: int = 0

class UserProgress(BaseModel):
    user_id: str
    level: int
    exp: int
    achievements: Optional[list[Achievement]] = None

# --- ENDPOINTS ---
@app.post("/register")
async def register_user(username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    """Регистрация нового пользователя
    - username: имя пользователя
    - email: электронная почта
    - password: пароль
    Возвращает user_id, токен и информацию о пользователе"""
    import uuid
    user_id = str(uuid.uuid4())
    token = str(uuid.uuid4())  # В реальном приложении использовать JWT
    created_at = datetime.now(timezone.utc)

    try:
        # Проверяем, не существует ли уже пользователь с таким email
        cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

        try:
            # Начинаем транзакцию
            cursor.execute("""
                INSERT INTO users (user_id, username, email, password, created_at, level, exp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, email, password, created_at, 1, 0))

            # Добавляем роль по умолчанию
            cursor.execute(
                "INSERT INTO roles (user_id, role) VALUES (?, ?)",
                (user_id, 'user')
            )

            # Подтверждаем транзакцию
            conn.commit()

            # Возвращаем данные для входа
            return {
                "token": token,
                "user_id": user_id,
                "username": username,
                "email": email,
                "role": "user",
                "level": 1,
                "exp": 0,
                "created_at": created_at.isoformat()
            }

        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=f"Ошибка создания пользователя: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in register_user: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    """Авторизация пользователя
    - email: электронная почта
    - password: пароль
    Возвращает информацию о пользователе и его роль"""
    print(f"Login attempt with email: {email}")
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if not user:
        print(f"User not found with email: {email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    stored_password = user[3]  # Предполагая, что пароль хранится в 4-м столбце

    if password != stored_password:  # В реальном приложении использовать безопасное сравнение хэшей
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Проверяем роль пользователя
    cursor.execute("SELECT role FROM roles WHERE user_id = ?", (user[0],))
    role_data = cursor.fetchone()
    role = role_data[0] if role_data else "user"

    # Генерируем токен для пользователя
    token = str(uuid.uuid4())  # В реальном приложении использовать JWT

    return {
        "user_id": user[0],
        "username": user[1],
        "email": user[2],
        "role": role,
        "token": token  # Добавляем токен в ответ
    }

@app.post("/watch-progress")
def update_watch_progress(progress: WatchProgress):
    try:
        # Создаем новое соединение для этого запроса
        with sqlite3.connect("anime_data.db") as local_conn:
            local_cursor = local_conn.cursor()

            # Проверяем существование пользователя
            local_cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (progress.user_id,))
            if not local_cursor.fetchone():
                raise HTTPException(status_code=404, detail="User not found")

            # Получаем существующую запись
            local_cursor.execute("""
                SELECT title, image_url, status, episodes_watched
                FROM watch_progress
                WHERE user_id = ? AND anime_id = ?
            """, (progress.user_id, progress.anime_id))
            existing = local_cursor.fetchone()

            # Используем существующие значения если новые не предоставлены
            title = progress.title if progress.title is not None else (existing[0] if existing else None)
            image_url = progress.image_url if progress.image_url is not None else (existing[1] if existing else None)
            old_status = existing[2] if existing else None
            old_episodes = existing[3] if existing else 0

            # Определяем статус на основе прогресса просмотра
            status = progress.status
            if progress.total_episodes and progress.total_episodes > 0 and progress.episodes_watched >= progress.total_episodes:
                status = Status.COMPLETED

            # Обновляем прогресс просмотра
            local_cursor.execute("""
                INSERT INTO watch_progress (
                    user_id, anime_id, episodes_watched, total_episodes,
                    status, title, image_url, last_watch_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, anime_id)
                DO UPDATE SET
                    episodes_watched = ?,
                    total_episodes = ?,
                    status = ?,
                    title = COALESCE(?, title),
                    image_url = COALESCE(?, image_url),
                    last_watch_date = CURRENT_TIMESTAMP
            """, (
                progress.user_id, progress.anime_id, progress.episodes_watched,
                progress.total_episodes, status, title, image_url,
                # Значения для ON CONFLICT UPDATE
                progress.episodes_watched, progress.total_episodes, status,
                title, image_url
            ))

            # Если статус изменился на completed или просмотрены все эпизоды
            if (old_status != Status.COMPLETED and status == Status.COMPLETED) or \
               (progress.episodes_watched > old_episodes):
                # Добавляем в историю просмотров
                local_cursor.execute("""
                    INSERT INTO recent (
                        user_id, anime_id, title, image_url
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, anime_id)
                    DO UPDATE SET
                        viewed_at = CURRENT_TIMESTAMP
                """, (progress.user_id, progress.anime_id, title, image_url))

                # Начисляем опыт за просмотр
                local_cursor.execute("""
                    UPDATE users
                    SET exp = exp + ?,
                        level = CASE
                            WHEN exp + ? >= level * 1000 THEN level + 1
                            ELSE level
                        END
                    WHERE user_id = ?
                """, (100, 100, progress.user_id))

            local_conn.commit()
            return {"message": "Progress updated successfully", "status": status}

    except sqlite3.Error as e:
        print(f"Database error in update_watch_progress: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        print(f"Error in update_watch_progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/watch-progress/{user_id}")
async def get_user_watch_progress(user_id: str):
    try:
        with conn:
            local_cursor = conn.cursor()
            # Проверяем существование пользователя
            local_cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if not local_cursor.fetchone():
                return {
                    "completed": [],
                    "inProgress": [],
                    "stats": {
                        "totalEpisodesWatched": 0,
                        "totalTimeSpent": 0,
                        "averageRating": 0,
                        "completed_count": 0,
                        "watching_count": 0
                    }
                }

        # Получаем аниме в процессе просмотра
        cursor.execute("""
            SELECT anime_id, title, image_url, status, episodes_watched, total_episodes,
                   last_watch_date
            FROM watch_progress
            WHERE user_id = ? AND status = 'watching'
            ORDER BY last_watch_date DESC
        """, (user_id,))
        in_progress = []
        for row in cursor.fetchall():
            in_progress.append({
                "animeId": row[0],
                "title": row[1],
                "image_url": row[2] or '/placeholder.svg',
                "status": row[3],
                "currentEpisode": row[4],
                "episodes": row[5],
                "lastWatched": row[6]
            })

        # Получаем завершенные аниме
        cursor.execute("""
            SELECT anime_id, title, image_url, episodes_watched, total_episodes,
                   last_watch_date
            FROM watch_progress
            WHERE user_id = ? AND status = 'completed'
            ORDER BY last_watch_date DESC
        """, (user_id,))
        completed = []
        for row in cursor.fetchall():
            completed.append({
                "animeId": row[0],
                "title": row[1],
                "image_url": row[2] or '/placeholder.svg',
                "episodes": row[3],
                "rating": 0,  # Пока нет системы рейтингов
                "completedAt": row[5]
            })

        # Собираем статистику
        cursor.execute("""
            SELECT
                SUM(episodes_watched) as total_episodes,
                COUNT(DISTINCT CASE WHEN status = 'completed' THEN anime_id END) as completed_count,
                COUNT(DISTINCT CASE WHEN status = 'watching' THEN anime_id END) as watching_count
            FROM watch_progress
            WHERE user_id = ?
        """, (user_id,))
        stats_row = cursor.fetchone()

        stats = {
            "totalEpisodesWatched": stats_row[0] or 0,
            "totalTimeSpent": (stats_row[0] or 0) * 24 * 60,  # Примерно 24 минуты на эпизод
            "averageRating": 0,  # Пока нет системы рейтингов
            "completed_count": stats_row[1] or 0,
            "watching_count": stats_row[2] or 0
        }

        return {
            "completed": completed,
            "inProgress": in_progress,
            "stats": stats
        }

    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/episode-progress")
def update_episode_progress(progress: EpisodeProgress):
    try:
        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episode_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                anime_id TEXT,
                episode_number INTEGER,
                progress REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, anime_id, episode_number)
            )
        """)
        # Insert or update episode progress
        cursor.execute("""
            INSERT INTO episode_progress (user_id, anime_id, episode_number, progress, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, anime_id, episode_number)
            DO UPDATE SET
                progress = ?,
                timestamp = ?
        """, (
            progress.user_id,
            progress.anime_id,
            progress.episode_number,
            progress.progress,
            datetime.now(timezone.utc).isoformat(),
            progress.progress,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        return {"message": "Episode progress updated"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-stats/{user_id}")
def get_user_stats(user_id: str):
    cursor.execute("""
        SELECT
            COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
            COUNT(CASE WHEN status = 'watching' THEN 1 END) as watching,
            COUNT(CASE WHEN status = 'planned' THEN 1 END) as planned,
            COUNT(CASE WHEN status = 'dropped' THEN 1 END) as dropped,
            SUM(episodes_watched) as total_episodes_watched
        FROM watch_progress
        WHERE user_id = ?
    """, (user_id,))

    stats = cursor.fetchone()
    return {
        "completed_anime": stats[0],
        "watching_anime": stats[1],
        "planned_anime": stats[2],
        "dropped_anime": stats[3],
        "total_episodes_watched": stats[4] or 0
    }

@app.get("/recent/{user_id}")
async def get_recent_anime(user_id: str):
    cursor.execute("""        SELECT anime_id, title, image_url, viewed_at
        FROM recent
        WHERE user_id = ?
        ORDER BY viewed_at DESC
        LIMIT 100
    """, (user_id,))

    results = cursor.fetchall()
    recent_list = []

    for row in results:
        recent_list.append({
            "anime_id": row[0],
            "title": row[1],
            "image_url": row[2],
            "viewed_at": row[3]
        })

    return recent_list

# Создаем таблицу recent если её нет
cursor.execute("""
    DROP TABLE IF EXISTS recent
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS recent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        anime_id TEXT,
        title TEXT,
        image_url TEXT,
        viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        UNIQUE(user_id, anime_id)
    )
""")
conn.commit()

@app.post("/recent")
async def add_recent_anime(data: RecentAnime):
    try:
        with conn:
            local_cursor = conn.cursor()
            # Проверяем существование пользователя
            local_cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (data.user_id,))
            if not local_cursor.fetchone():
                raise HTTPException(status_code=404, detail="User not found")

            # Добавляем или обновляем запись
            local_cursor.execute("""
                INSERT INTO recent (user_id, anime_id, title, image_url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, anime_id)
                DO UPDATE SET
                    title = ?,
                    image_url = ?,
                    viewed_at = CURRENT_TIMESTAMP
            """, (
                data.user_id, data.anime_id, data.title, data.image_url,
                data.title, data.image_url
            ))

            return {"message": "Recent anime added successfully"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/favorites/{user_id}")
async def update_favorites(user_id: str, data: FavoriteAction):
    """Добавление или удаление аниме из избранного"""
    print(f"Received favorites request for user {user_id}: {data.dict()}")

    try:
        # Проверяем существование пользователя
        cursor.execute("""
            SELECT username FROM users WHERE user_id = ?
        """, (user_id,))
        user = cursor.fetchone()

        if not user:
            print(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        print(f"User found: {user[0]}")

        if data.action not in ["add", "remove"]:
            raise HTTPException(status_code=400, detail="Недопустимое действие")

        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")

        try:
            is_exists = False  # Ensure is_exists is always defined
            if data.action == "add":
                if not data.title or not data.animeId:
                    raise HTTPException(
                        status_code=400,
                        detail="Требуется указать название и ID аниме"
                    )

                print(f"Adding anime to favorites: {data.title} ({data.animeId})")

                # Проверяем, существует ли уже в избранном
                cursor.execute("""
                    SELECT 1 FROM favorites
                    WHERE user_id = ? AND anime_id = ?
                """, (user_id, data.animeId))
                
                is_exists = cursor.fetchone() is not None

                if is_exists:
                    print("Updating existing favorite")
                    cursor.execute("""
                        UPDATE favorites
                        SET title = ?, image_url = ?, created_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND anime_id = ?
                    """, (data.title, data.image_url, user_id, data.animeId))
                else:
                    print("Inserting new favorite")
                    cursor.execute("""
                        INSERT INTO favorites (user_id, anime_id, title, image_url)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, data.animeId, data.title, data.image_url))

            elif data.action == "remove":
                print(f"Removing anime from favorites: {data.animeId}")
                cursor.execute("""
                    DELETE FROM favorites
                    WHERE user_id = ? AND anime_id = ?
                """, (user_id, data.animeId))

            # Проверяем, были ли изменения
            if cursor.rowcount == 0:
                if data.action == "remove":
                    print("No favorite found to remove")
                    raise HTTPException(
                        status_code=404,
                        detail="Аниме не найдено в избранном"
                    )
                elif data.action == "add" and is_exists:
                    print("No changes made to existing favorite")

            conn.commit()
            print("Transaction committed successfully")

            # Получаем обновленный список избранного
            cursor.execute("""
                SELECT anime_id, title, image_url, created_at
                FROM favorites
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))

            favorites = [{
                "id": row[0],
                "title": row[1],
                "image": row[2] or '/placeholder.svg',
                "addedAt": row[3]
            } for row in cursor.fetchall()]

            return {
                "status": "success",
                "action": data.action,
                "count": len(favorites),
                "favorites": favorites
            }

        except sqlite3.IntegrityError as e:
            print(f"Database integrity error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Ошибка целостности данных: {str(e)}"
            )
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка базы данных: {str(e)}"
            )
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Внутренняя ошибка сервера: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in update_favorites: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

@app.post("/watch-status/{user_id}")
async def update_watch_status(user_id: str, data: WatchStatusUpdate):
    try:
        if data.status not in ['planned', 'watching', 'completed', 'dropped']:
            raise HTTPException(status_code=422, detail="Invalid status value")

        print(f"Received watch status update: {data.dict()}")

        # Проверяем наличие обязательных полей
        if not data.title or not data.image_url:
            raise HTTPException(status_code=400, detail="Title and image_url are required")

        cursor.execute("""
            INSERT INTO watch_progress
            (user_id, anime_id, title, image_url, status, episodes_watched, last_watch_date)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, anime_id)
            DO UPDATE SET
                status = ?,
                episodes_watched = ?,
                title = ?,
                image_url = COALESCE(?, image_url),  -- Используем существующее значение если новое пустое
                last_watch_date = datetime('now')
        """, (
            user_id,
            data.animeId,
            data.title,
            data.image_url or '/placeholder.svg',  # Используем placeholder если image_url пустой
            data.status,
            data.episodes,
            data.status,
            data.episodes,
            data.title,
            data.image_url
        ))

        conn.commit()

        cursor.execute("""
            SELECT
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as watched_count,
                COUNT(CASE WHEN status = 'watching' THEN 1 END) as in_progress_count
            FROM watch_progress
            WHERE user_id = ?
        """, (user_id,))

        stats = cursor.fetchone()
        return {
            "status": "success",
            "watched_count": stats[0] or 0,
            "in_progress_count": stats[1] or 0
        }

    except sqlite3.Error as e:
        print(f"Database error in update_watch_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"Error in update_watch_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/watch-status/{user_id}/{anime_id}")
async def delete_watch_status(user_id: str, anime_id: str):
    try:
        cursor.execute("""
            DELETE FROM watch_progress
            WHERE user_id = ? AND anime_id = ?
        """, (user_id, anime_id))
        conn.commit()
        return {"status": "deleted"}
    except sqlite3.Error as e:
        print(f"Database error in delete_watch_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"Error in delete_watch_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/watched-list/{user_id}")
async def get_watched_list(user_id: str):
    try:
        cursor.execute("""
            SELECT anime_id, title, image_url, episodes_watched, total_episodes,
                   last_watch_date
            FROM watch_progress
            WHERE user_id = ? AND status = 'completed'
            ORDER BY last_watch_date DESC
        """, (user_id,))

        watched = []
        for row in cursor.fetchall():
            watched.append({
                "animeId": row[0],
                "title": row[1],
                "image_url": row[2] or '/placeholder.svg',
                "episodes": row[3],
                "total_episodes": row[4],
                "completed_at": row[5]
            })

        return watched
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/stats/{user_id}")
async def get_user_statistics(user_id: str):
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM favorites WHERE user_id = ?
        """, (user_id,))
        favorites_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                COUNT(CASE WHEN status = 'watching' THEN 1 END) as watching
            FROM watch_progress
            WHERE user_id = ?
        """, (user_id,))
        watch_stats = cursor.fetchone()

        return {
            "favorites_count": favorites_count,
            "watched_count": watch_stats[0] or 0,
            "in_progress_count": watch_stats[1] or 0
        }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/user/{user_id}")
async def update_user(user_id: str, data: UserUpdate):
    try:
        cursor.execute("""
            INSERT INTO users (user_id, username, email)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = ?,
                email = ?
        """, (user_id, data.username, data.email.lower() if data.email else None, 
             data.username, data.email.lower() if data.email else None))
        conn.commit()
        return {"status": "success"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    cursor.execute("SELECT user_id, username, email, avatar_path, created_at FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        user = {
            "user_id": row[0],
            "username": row[1],
            "email": row[2],
            "avatar_url": row[3],
            "created_at": row[4]
        }
        return user
    else:
        raise HTTPException(status_code=404, detail="User not found")

@app.post("/avatar/{user_id}")
async def upload_avatar(user_id: str, file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        file_ext = os.path.splitext(file.filename)[1]
        avatar_name = f"{user_id}{file_ext}"
        file_path = AVATARS_DIR / avatar_name
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        avatar_url = f"/avatars/{avatar_name}"
        # Только обновляем avatar_path, не вставляем новую строку!
        cursor.execute("""
            UPDATE users SET avatar_path = ? WHERE user_id = ?
        """, (avatar_url, user_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        conn.commit()
        return {
            "status": "success",
            "avatar_path": avatar_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/avatar/{user_id}")
async def get_avatar(user_id: str):
    try:
        cursor.execute("SELECT avatar_path FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return {
            "avatar_path": row[0] if row and row[0] else None
        }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-profile/{user_id}")
async def update_profile(
    user_id: str,
    username: str = Form(...),
    email: str = Form(...),
    avatar: Optional[UploadFile] = File(None)
):
    try:
        normalized_email = email.lower() if email else None
        if avatar and avatar.filename:
            file_ext = os.path.splitext(avatar.filename)[1]
            avatar_name = f"{user_id}{file_ext}"
            file_path = AVATARS_DIR / avatar_name
            with file_path.open("wb") as buffer:
                content = await avatar.read()
                buffer.write(content)
            avatar_url = f"/avatars/{avatar_name}"
        else:
            avatar_url = None
        cursor.execute("""
            UPDATE users
            SET username = ?,
                email = ?,
                avatar_path = COALESCE(?, avatar_path)
            WHERE user_id = ?
        """, (username, normalized_email, avatar_url, user_id))
        conn.commit()
        return {
            "status": "success",
            "message": "Profile updated successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/watched/{user_id}")
async def get_watched_anime(user_id: str):
    try:
        cursor.execute("""
            SELECT anime_id, title, image_url
            FROM watch_progress
            WHERE user_id = ? AND status = 'completed'
            ORDER BY last_watch_date DESC
        """, (user_id,))

        watched = cursor.fetchall()

        return [
            {
                "anime_id": row[0],
                "title": row[1],
                "image_url": row[2]
            }
            for row in watched
        ]
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def head_root():
    return {"message": "AnimeWatch API"}


@app.get("/debug/users")
async def debug_users():
    try:
        cursor.execute("SELECT user_id, username, email FROM users")
        users = cursor.fetchall()
        return {"users": [{"user_id": u[0], "username": u[1], "email": u[2]} for u in users]}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/setup")
async def setup_admin(data: AdminSetup):
    SETUP_KEY = "your-secret-setup-key"  # Замените на реальный секретный ключ
    try:
        if data.setupKey != SETUP_KEY:
            raise HTTPException(status_code=401, detail="Invalid setup key")

        # Проверяем существование пользователя
        cursor.execute("SELECT user_id FROM users WHERE email = ?", (data.email.lower(),))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user[0]

        # Проверяем, есть ли уже администраторы
        cursor.execute("SELECT COUNT(*) FROM administrators")
        admin_count = cursor.fetchone()[0]
        if admin_count > 0:
            raise HTTPException(status_code=400, detail="Administrator already exists")

        # Добавляем пользователя в таблицу administrators
        cursor.execute("INSERT INTO administrators (user_id) VALUES (?)", (user_id,))

        # Обновляем роль пользователя
        cursor.execute("""
            INSERT INTO roles (user_id, role)
            VALUES (?, 'admin')
            ON CONFLICT(user_id) DO UPDATE SET
                role = 'admin'
        """, (user_id,))

        conn.commit()
        return {"status": "success", "message": "Administrator setup completed"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/reset")
async def reset_admin(data: AdminSetup):
    SETUP_KEY = "your-secret-setup-key"  # Тот же ключ, что и для setup
    try:
        if data.setupKey != SETUP_KEY:
            raise HTTPException(status_code=401, detail="Invalid setup key")

        # Удаляем всех администраторов
        cursor.execute("DELETE FROM administrators")
        cursor.execute("UPDATE roles SET role = 'user'")
        conn.commit()

        return {"status": "success", "message": "Administrator reset completed"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/check/{user_id}")
async def check_admin_status(user_id: str):
    try:
        cursor.execute("""
            SELECT u.user_id, u.email, r.role
            FROM users u
            LEFT JOIN roles r ON u.user_id = r.user_id
            WHERE u.user_id = ?
        """, (user_id,))

        result = cursor.fetchone()
        if not result:
            return {"isAdmin": False}

        return {
            "isAdmin": result[2] == "admin" if result[2] else False
        }
    except sqlite3.Error as e:
        print(f"Database error in check_admin_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/stats")
async def get_admin_stats():
    try:
        # Считаем пользователей с ролью user
        cursor.execute("SELECT COUNT(*) FROM roles WHERE role = 'user'")
        users_count = cursor.fetchone()[0] or 0

        # Считаем пользователей с ролью admin
        cursor.execute("SELECT COUNT(*) FROM roles WHERE role = 'admin'")
        admins_count = cursor.fetchone()[0] or 0

        return {
            "users": users_count,
            "admins": admins_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/users")
async def get_admin_users():
    try:
        cursor.execute("""
            SELECT u.user_id, u.username, u.email, u.avatar_path, COALESCE(r.role, 'user') as role, u.created_at
            FROM users u
            LEFT JOIN roles r ON u.user_id = r.user_id
            ORDER BY u.username
        """)
        users = cursor.fetchall()
        return [
            {
                "id": user[0],
                "username": user[1],
                "email": user[2],
                "avatar_url": user[3] if user[3] else None,
                "role": user[4],
                "created_at": user[5]
            }
            for user in users
        ]
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/admin/users/{user_id}/role")
async def update_admin_user_role(user_id: str, role_data: UserRole):
    try:
        # Проверяем существование пользователя
        cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        cursor.execute("""
            INSERT INTO roles (user_id, role)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET role = ?
        """, (user_id, role_data.role, role_data.role))

        # Обновляем таблицу administrators
        if role_data.role == "admin":
            cursor.execute("""
                INSERT INTO administrators (user_id)
                VALUES (?) ON CONFLICT(user_id) DO NOTHING
            """, (user_id,))
        else:
            cursor.execute("DELETE FROM administrators WHERE user_id = ?", (user_id,))

        conn.commit()
        return {"status": "success", "message": "Role updated successfully"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/favorites/{user_id}")
async def get_favorites(user_id: str):
    """Получение списка избранного для пользователя"""
    try:
        cursor.execute("""
            SELECT anime_id, title, image_url, created_at
            FROM favorites
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        rows = cursor.fetchall()
        return [
            {
                "anime_id": row[0],
                "title": row[1],
                "image_url": row[2],
                "created_at": row[3]
            }
            for row in rows
        ]
    except sqlite3.Error as e:
        print(f"Database error in get_favorites: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"Error in get_favorites: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/favorites/{user_id}/manage")
async def manage_favorites(user_id: str, data: FavoriteAction):
    """Добавление или удаление аниме из избранного"""
    print(f"Received favorites request for user {user_id}: {data.dict()}")

    try:
        # Проверяем существование пользователя
        cursor.execute("""
            SELECT username FROM users WHERE user_id = ?
        """, (user_id,))
        user = cursor.fetchone()

        if not user:
            print(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if data.action not in ["add", "remove"]:
            raise HTTPException(status_code=400, detail="Недопустимое действие")

        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")

        try:
            result_status = False
            
            if data.action == "add":
                if not data.title or not data.animeId:
                    raise HTTPException(
                        status_code=400,
                        detail="Требуется указать название и ID аниме"
                    )

                print(f"Adding anime to favorites: {data.title} ({data.animeId})")

                # Проверяем, существует ли уже в избранном
                cursor.execute("""
                    SELECT 1 FROM favorites
                    WHERE user_id = ? AND anime_id = ?
                """, (user_id, data.animeId))

                if cursor.fetchone():
                    print("Updating existing favorite")
                    cursor.execute("""
                        UPDATE favorites
                        SET title = ?, image_url = ?, created_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND anime_id = ?
                    """, (data.title, data.image_url, user_id, data.animeId))
                    result_status = cursor.rowcount > 0
                else:
                    print("Inserting new favorite")
                    cursor.execute("""
                        INSERT INTO favorites (user_id, anime_id, title, image_url)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, data.animeId, data.title, data.image_url))
                    result_status = True

            elif data.action == "remove":
                print(f"Removing anime from favorites: {data.animeId}")
                cursor.execute("""
                    DELETE FROM favorites
                    WHERE user_id = ? AND anime_id = ?
                """, (user_id, data.animeId))
                result_status = cursor.rowcount > 0

            if not result_status and data.action == "remove":
                print("No favorite found to remove")
                raise HTTPException(
                    status_code=404,
                    detail="Аниме не найдено в избранном"
                )

            conn.commit()
            print("Transaction committed successfully")

            # Получаем обновленный список избранного
            cursor.execute("""
                SELECT anime_id, title, image_url, created_at
                FROM favorites
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))

            favorites = [{
                "id": row[0],
                "title": row[1],
                "image": row[2] or '/placeholder.svg',
                "addedAt": row[3]
            } for row in cursor.fetchall()]

            return {
                "status": "success",
                "action": data.action,
                "count": len(favorites),
                "favorites": favorites
            }

        except sqlite3.IntegrityError as e:
            print(f"Database integrity error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Ошибка целостности данных: {str(e)}"
            )
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка базы данных: {str(e)}"
            )
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Внутренняя ошибка сервера: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in update_favorites: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

@app.post("/now-watching")
async def add_now_watching(entry: NowWatchingEntry):
    try:
        cursor.execute("""
            INSERT INTO now_watching (anime_id, title, image_url, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(anime_id) DO UPDATE SET
                title=excluded.title,
                image_url=excluded.image_url,
                updated_at=CURRENT_TIMESTAMP
        """, (entry.anime_id, entry.title, entry.image_url))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/now-watching")
async def get_now_watching(limit: int = 10):
    try:
        cursor.execute("""
            SELECT anime_id, title, image_url
            FROM now_watching
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [
            {"anime_id": row[0], "title": row[1], "image_url": row[2]}
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reviews")
async def add_review(review: Review):
    try:
        cursor.execute(
            "INSERT INTO reviews (username, text) VALUES (?, ?)",
            (review.username, review.text)
        )
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/reviews")
async def get_reviews(limit: int = 20, offset: int = 0):
    cursor.execute(
        "SELECT username, text, created_at FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    rows = cursor.fetchall()
    return [
        {"username": row[0], "text": row[1], "created_at": row[2]} for row in rows
    ]

@app.get("/admin/new-users-week")
async def get_new_users_week():
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=6)
    cursor.execute(
        """
        SELECT DATE(created_at) as reg_date, COUNT(*) as count
        FROM users
        WHERE DATE(created_at) BETWEEN ? AND ?
        GROUP BY reg_date
        ORDER BY reg_date ASC
        """,
        (week_ago.isoformat(), today.isoformat())
    )
    rows = cursor.fetchall()
    # Формируем словарь: {date: count}
    date_counts = {row[0]: row[1] for row in rows}
    # Гарантируем, что будут все 7 дней (даже если 0)
    result = []
    for i in range(7):
        d = (week_ago + timedelta(days=i)).isoformat()
        result.append({"date": d, "count": date_counts.get(d, 0)})
    return result

@app.post("/admin/news")
async def create_news(news: News):
    cursor.execute(
        "INSERT INTO news (title, description, author) VALUES (?, ?, ?)",
        (news.title, news.description, news.author)
    )
    conn.commit()
    return {"status": "success"}

@app.get("/admin/news")
async def get_news():
    cursor.execute("SELECT id, title, description, author, created_at FROM news ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [
        {"id": row[0], "title": row[1], "description": row[2], "author": row[3], "created_at": row[4]}
        for row in rows
    ]

@app.delete("/admin/news/{news_id}")
async def delete_news(news_id: int):
    cursor.execute("DELETE FROM news WHERE id = ?", (news_id,))
    conn.commit()
    return {"status": "success"}

@app.get("/news")
async def get_public_news():
    cursor.execute("SELECT title, description, author, created_at FROM news ORDER BY created_at DESC LIMIT 5")
    rows = cursor.fetchall()
    return [
        {"title": row[0], "description": row[1], "author": row[2], "created_at": row[3]}
        for row in rows
    ]

@app.get("/admin/users-cumulative")
async def users_cumulative():
    today = date.today()
    days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
    labels = [d.strftime('%d.%m') for d in days]
    data = []
    for d in days:
        cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) <= ?", (d.isoformat(),))
        count = cursor.fetchone()[0]
        data.append(count)
    return {"labels": labels, "data": data}

# --- ACHIEVEMENTS AND LEVELS ENDPOINTS ---

@app.post("/achievements")
async def create_achievement(achievement: Achievement):
    """Создание нового достижения (только для администраторов)"""
    try:
        cursor.execute(
            "INSERT INTO achievements (name, description, icon_path, exp_reward) VALUES (?, ?, ?, ?)",
            (achievement.name, achievement.description, achievement.icon_path, achievement.exp_reward)
        )
        conn.commit()
        return {"status": "success", "id": cursor.lastrowid}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/achievements")
async def get_all_achievements():
    """Получение списка всех достижений"""
    cursor.execute("SELECT id, name, description, icon_path, exp_reward FROM achievements")
    achievements = cursor.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "icon_path": row[3],
            "exp_reward": row[4]
        }
        for row in achievements
    ]

@app.get("/user/{user_id}/achievements")
async def get_user_achievements(user_id: str):
    """Получение достижений конкретного пользователя"""
    cursor.execute("""
        SELECT a.id, a.name, a.description, a.icon_path, a.exp_reward, ua.unlocked_at
        FROM achievements a
        JOIN user_achievements ua ON a.id = ua.achievement_id
        WHERE ua.user_id = ?
    """, (user_id,))
    achievements = cursor.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "icon_path": row[3],
            "exp_reward": row[4],
            "unlocked_at": row[5]
        }
        for row in achievements
    ]

@app.post("/user/{user_id}/achievements/{achievement_id}")
async def unlock_achievement(user_id: str, achievement_id: int):
    """Разблокировка достижения для пользователя"""
    try:
        # Добавляем достижение пользователю
        cursor.execute(
            "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
            (user_id, achievement_id)
        )

        # Получаем награду за достижение
        cursor.execute("SELECT exp_reward FROM achievements WHERE id = ?", (achievement_id,))
        exp_reward = cursor.fetchone()[0]

        # Обновляем опыт пользователя
        cursor.execute("""
            UPDATE users
            SET exp = exp + ?,
                level = CASE
                    WHEN exp + ? >= level * 1000 THEN level + 1
                    ELSE level
                END
            WHERE user_id = ?
        """, (exp_reward, exp_reward, user_id))

        conn.commit()
        return {"status": "success", "exp_gained": exp_reward}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/{user_id}/progress")
async def get_user_progress(user_id: str):
    """Получение прогресса пользователя (уровень, опыт, достижения)"""
    cursor.execute("SELECT level, exp FROM users WHERE user_id = ?", (user_id,))
    progress = cursor.fetchone()
    if not progress:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "level": progress[0],
        "exp": progress[1],
        "next_level_exp": progress[0] * 1000
    }

# --- IMPROVED WATCHED ANIME ENDPOINTS ---

@app.get("/watched-anime/global")
async def get_global_watched_anime(limit: int = 10):
    """Получение глобальной статистики по просмотренным аниме"""
    cursor.execute("""
        SELECT anime_id, title, image_url, COUNT(*) as watch_count
        FROM watch_progress
        WHERE status = 'completed'
        GROUP BY anime_id, title, image_url
        ORDER BY watch_count DESC
        LIMIT ?
    """, (limit,))
    return [
        {
            "anime_id": row[0],
            "title": row[1],
            "image_url": row[2],
            "watch_count": row[3]
        }
        for row in cursor.fetchall()
    ]

@app.get("/user/{user_id}/watched-detailed")
async def get_user_watched_detailed(user_id: str):
    """Получение детальной информации о просмотренных аниме пользователя"""
    cursor.execute("""
        SELECT
            wp.anime_id,
            wp.title,
            wp.image_url,
            wp.episodes_watched,
            wp.status,
            wp.last_watch_date,
            CASE WHEN f.anime_id IS NOT NULL THEN 1 ELSE 0 END as is_favorite
        FROM watch_progress wp
        LEFT JOIN favorites f ON wp.anime_id = f.anime_id AND wp.user_id = f.user_id
        WHERE wp.user_id = ?
        ORDER BY wp.last_watch_date DESC
    """, (user_id,))

    return [
        {
            "anime_id": row[0],
            "title": row[1],
            "image_url": row[2],
            "episodes_watched": row[3],
            "status": row[4],
            "last_watch_date": row[5],
            "is_favorite": bool(row[6])
        }
        for row in cursor.fetchall()
    ]

@app.get("/user/{user_id}/favorites-detailed")
async def get_user_favorites_detailed(user_id: str):
    """Получение детальной информации об избранных аниме пользователя"""
    cursor.execute("""
        SELECT
            f.anime_id,
            f.title,
            f.image_url,
            COUNT(wp.anime_id) as episodes_watched,
            MAX(wp.last_watch_date) as last_watch_date
        FROM favorites f
        LEFT JOIN watch_progress wp ON f.anime_id = wp.anime_id AND f.user_id = wp.user_id
        WHERE f.user_id = ?
        GROUP BY f.anime_id, f.title, f.image_url
        ORDER BY MAX(wp.last_watch_date) DESC
    """, (user_id,))

    return [
        {
            "anime_id": row[0],
            "title": row[1],
            "image_url": row[2],
            "episodes_watched": row[3] or 0,
            "last_watch_date": row[4]
        }
        for row in cursor.fetchall()
    ]


@app.post("/user/{user_id}/watch-episode")
async def watch_episode(user_id: str):
    """Начисление опыта за просмотр эпизода"""
    try:
        # Проверяем существование пользователя
        cursor.execute("""
            SELECT level, exp
            FROM users
            WHERE user_id = ?
        """, (user_id,))
        user_data = cursor.fetchone()

        if not user_data:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        current_level, current_exp = user_data
        exp_per_episode = 100  # Опыт за просмотр одного эпизода
        next_level_exp = 1000 * current_level  # Опыт для следующего уровня

        # Начисляем опыт
        new_exp = current_exp + exp_per_episode
        new_level = current_level

        # Проверяем, нужно ли повысить уровень
        while new_exp >= next_level_exp:
            new_level += 1
            new_exp -= next_level_exp
            next_level_exp = 1000 * new_level

        # Обновляем данные пользователя
        cursor.execute("""
            UPDATE users
            SET level = ?, exp = ?
            WHERE user_id = ?
        """, (new_level, new_exp, user_id))

        conn.commit()

        return {
            "level": new_level,
            "exp": new_exp,
            "next_level_exp": next_level_exp
        }
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error in watch_episode: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        conn.rollback()
        print(f"Error in watch_episode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
