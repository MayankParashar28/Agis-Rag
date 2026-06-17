import uuid
from datetime import timedelta
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from jose import jwt

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, oauth2_scheme, decode_token
from app.models.auth import User
from app.schemas.auth import UserResponse, UserCreate, UserLogin, UserUpdate, Token
from app.core.email import send_verification_email

router = APIRouter()

# Dependency to get current user from JWT token
async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Try decoding token using Neon Auth or local auth
    user_id_or_email = await decode_token(token)
    if not user_id_or_email:
        raise credentials_exception

    # If the token is from Neon Auth, it might contain the user ID or email. 
    # For robust matching, we assume Neon Auth uses string IDs. Since our DB uses UUID, 
    # we can try to parse it as UUID. If it fails, it's a Neon Auth ID, so we fall back 
    # to email matching if the token had an email claim.
    
    # Let's decode the payload again without verification just to extract email if it exists
    try:
        unverified_payload = jwt.get_unverified_claims(token)
        email = unverified_payload.get("email")
    except:
        email = None

    try:
        # If it's a valid UUID, query by ID
        parsed_uuid = uuid.UUID(user_id_or_email)
        result = await db.execute(select(User).where(User.id == parsed_uuid))
        user = result.scalar_one_or_none()
    except ValueError:
        # Not a UUID, so it must be a Neon Auth string ID. Look up by email if available.
        user = None
        if email:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            
            # Auto-provision if missing
            if not user:
                user = User(
                    email=email,
                    hashed_password="NEON_AUTH_MANAGED",
                    full_name=unverified_payload.get("name", "Neon User"),
                    role="user",
                    is_active=True
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)

    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges"
        )
    return current_user


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    # Check if user already exists
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalar_one_or_none()
    if user:
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists in the system.",
        )
    
    # Check if this is the first user in the system to bootstrap admin role
    users_count_res = await db.execute(select(func.count(User.id)))
    users_count = users_count_res.scalar() or 0
    role = "admin" if users_count == 0 else "user"
    
    db_obj = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=role,
        is_active=True,
        email_verified=True
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)

    return db_obj


from pydantic import BaseModel
class VerifyEmailRequest(BaseModel):
    token: str

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    email_or_id = decode_token(req.token)
    if not email_or_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    
    result = await db.execute(select(User).where(User.email == email_or_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.email_verified:
        return {"msg": "Email already verified"}
        
    user.email_verified = True
    await db.commit()
    return {"msg": "Email verified successfully"}

class ResendVerificationRequest(BaseModel):
    email: str

@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"msg": "If the email is registered, a verification link has been sent."}
        
    if user.email_verified:
        return {"msg": "Email already verified."}
        
    expires_delta = timedelta(days=1)
    verify_token = create_access_token(subject=req.email, expires_delta=expires_delta)
    
    try:
        await send_verification_email(to_email=req.email, token=verify_token)
    except Exception as e:
        import logging
        logging.error(f"Failed to resend email for {req.email}: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email")
        
    return {"msg": "If the email is registered, a verification link has been sent."}




@router.post("/login", response_model=Token)
async def login(user_in: UserLogin, db: AsyncSession = Depends(get_db)) -> Any:
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


from pydantic import BaseModel, EmailStr
class GoogleToken(BaseModel):
    id_token: str
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None

@router.post("/google", response_model=Token)
async def google_login(token_in: GoogleToken, db: AsyncSession = Depends(get_db)) -> Any:
    # Google OAuth token verification placeholder.
    # In production, we'd use oauth2.verify_oauth2_token(token_in.id_token, requests.Request(), GOOGLE_CLIENT_ID)
    # For simulation/mock: we'll parse/mock verify the token or construct a mock user if id_token matches a mock pattern.
    mock_email = f"google_{token_in.id_token.split('.')[0]}@example.com" if "." in token_in.id_token else "google_user@example.com"
    mock_name = token_in.full_name or "Google User"
    
    result = await db.execute(select(User).where(User.email == mock_email))
    user = result.scalar_one_or_none()
    
    if not user:
        # Auto-signup google user
        user = User(
            email=mock_email,
            hashed_password=get_password_hash(uuid.uuid4().hex), # random password
            full_name=mock_name,
            role="user",
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """
    Retrieve all users. Restricted to admin.
    """
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return users


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Update a user.
    - Standard active users can only update their own profile (name, email).
    - Admins can update any user's role and active status.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    # Permission checks
    is_admin = current_user.role == "admin"
    is_self = current_user.id == user.id
    
    if not is_admin and not is_self:
        raise HTTPException(
            status_code=403,
            detail="Not enough privileges to update this user"
        )
    
    # Apply updates
    if user_in.full_name is not None:
        user.full_name = user_in.full_name
    if user_in.email is not None:
        # Check if email is already taken by another user
        email_check = await db.execute(select(User).where(User.email == user_in.email, User.id != user_id))
        if email_check.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists."
            )
        user.email = user_in.email
        
    # Admin-only fields
    if user_in.role is not None:
        if not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can update user roles"
            )
        # Prevent demoting the last admin to user
        if user.role == "admin" and user_in.role != "admin":
            # Check if there's at least one other active admin
            admin_count_res = await db.execute(
                select(func.count(User.id)).where(User.role == "admin", User.is_active == True, User.id != user_id)
            )
            admin_count = admin_count_res.scalar() or 0
            if admin_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote the last active administrator"
                )
        user.role = user_in.role
        
    if user_in.is_active is not None:
        if not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can change active status"
            )
        # Prevent deactivating the last active admin
        if user.role == "admin" and not user_in.is_active:
            admin_count_res = await db.execute(
                select(func.count(User.id)).where(User.role == "admin", User.is_active == True, User.id != user_id)
            )
            admin_count = admin_count_res.scalar() or 0
            if admin_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot deactivate the last active administrator"
                )
        user.is_active = user_in.is_active
        
    await db.commit()
    await db.refresh(user)
    return user

